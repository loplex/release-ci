#!/usr/bin/env python3
"""What a release has to be true of, checked before and after it is one.

- `version` - whether the version the project declares may be released next, given the tags it already has.
- `next` - the version to be worked on once one is released.
- `changelog` - whether every section already released still reads the way it was released.
- `ancestry` - whether every released tag is still reachable, a rewrite being able to take one off the history.
- `prefix` - what release tags are called here, so that the workflows do not have to say it a second time.
- `channel` - the distribution channel a version goes to, read off its pre-release suffix.
- `set-version` - write the version the project declares, which is what a release does.

All of it sits on plain functions over text, tags and booleans, so that the rules can be exercised without a
repository to release. The tests beside this file are what exercises them.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

def repository_root() -> Path:
    """The repository being checked, which is not the same question as where this file lives.

    This file is meant to be run from a checkout of its own repository against some other one, and a root
    taken from its own path would then name the wrong repository - quietly, the moment this one carried a
    gradle.properties or a CHANGELOG.md of its own. So the root is asked of git in the working directory, and
    nothing here assumes where the file sits.
    """
    found = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if found.returncode != 0:
        raise SystemExit("check-release.py has to be run inside the repository it is checking")
    return Path(found.stdout.strip())


# Resolved on first use rather than when this file is loaded, so that `--help` answers anywhere and the tests
# can stand a repository of their own in here before anything asks. A subcommand that reads the repository
# still refuses to run outside one; it just says so after the arguments have been read, not before.
REPO: Path | None = None


def repository() -> Path:
    global REPO
    if REPO is None:
        REPO = repository_root()
    return REPO

# What this project releases: a semantic version, build metadata included. The grammar is SemVer 2.0.0's
# own - no leading zeros, and a pre-release identifier is either a number or something carrying a letter or a
# hyphen - which is what lets precedence below order it the way the spec orders it; a shape the spec leaves
# undefined, `1.0.0-a..b` or `01.0.0`, would be sorted here by rules nobody wrote down. The spec's digits are
# ASCII ones and its version ends where the text does, so `re.ASCII` keeps `\d` from taking another script's
# digits - `1٠.0.0` would otherwise be ordered as 10.0.0 - and `\Z` keeps a trailing newline out, which `$`
# would let through.
#
# Build metadata - the `+` part - is taken, and the spec's rule about it is taken with it: "Build metadata
# MUST be ignored when determining version precedence." So `1.0.0+a` and `1.0.0+b` are both versions here and
# neither comes after the other, which check_version says in those words rather than leaving the reader with
# a refusal that looks like arithmetic. It is not part of the channel either: the suffix is what names that,
# and metadata is captured apart from it.
#
# The suffix is not decoration - it names the distribution channel the version is published to (see
# channel_of), so `0.2.0-beta.1` is offered only to whoever subscribed to `beta`, and a release carrying one
# is a pre-release wherever it is published.
IDENTIFIER = r"(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)"
BUILD = r"(?:[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)"
VERSION = re.compile(
    rf"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-({IDENTIFIER}(?:\.{IDENTIFIER})*))?(?:\+({BUILD}))?\Z",
    re.ASCII,
)

# The marker a version carries while it is being worked on. It is the one suffix that is not a channel: it says
# the version has not been released, so a release is precisely what it cannot be - check_version refuses a
# candidate still carrying it, and tags() leaves a tag carrying it out of what counts as released.
SNAPSHOT = "-SNAPSHOT"

# The one line of gradle.properties a release rewrites. Gradle allows space around the `=` and in front of the
# key, and projects write it every way, so everything up to the value is captured and put back rather than
# chosen here: turning one spelling into the other would show up in the diff as a change nobody made. The
# indentation is part of that and has to be, because properties() reads an indented line as a declaration -
# a writer that did not would refuse a file whose version it can see. The line ending is the same kind of
# thing: the value stops short of a carriage return, so a file written with CRLF keeps it.
VERSION_LINE = re.compile(r"^([ \t]*version[ \t]*=[ \t]*)([^\r\n]*)", re.MULTILINE)

SECTION = re.compile(r"^## \[([^\]]+)\]", re.MULTILINE)
LINK_DEFINITION = re.compile(r"^\[[^\]]+\]:\s.*$", re.MULTILINE)


def precedence(version: str) -> tuple:
    """Orders versions the way SemVer does, so that `<` and `sorted` mean what the spec means.

    Two rules are easy to get wrong by comparing strings: a release outranks every pre-release of the same three
    numbers (`0.2.0` > `0.2.0-rc.1`), and a numeric identifier inside a suffix is compared as a number rather
    than as text (`beta.9` < `beta.10`).

    Build metadata is dropped rather than ranked last, because the spec requires it: two versions differing
    only there have the same precedence. Everything reading this has to be able to cope with that equality -
    check_version is where it is met and named.
    """
    major, minor, patch, suffix, _ = VERSION.match(version).groups()
    if suffix is None:
        return (int(major), int(minor), int(patch), 1, ())

    identifiers = tuple(
        (0, int(part), "") if part.isdigit() else (1, 0, part) for part in suffix.split(".")
    )
    return (int(major), int(minor), int(patch), 0, identifiers)


def being_worked_on(version: str) -> bool:
    """Whether `version` carries the SNAPSHOT marker as an identifier of its pre-release suffix: `1.0.0-SNAPSHOT`,
    but also `1.0.0-rc.1-SNAPSHOT`, and `1.0.0-SNAPSHOT-SNAPSHOT`, which is what a script appending the marker
    to a version that already has it produces - and which the plain suffix strip in version_command turns into
    a candidate that still carries it. Split on both separators, so that `presnapshot` is not the marker and
    `rc.1-SNAPSHOT` is. Metadata is not looked at: it names a build, not a state."""
    suffix = VERSION.match(version).group(4) or ""
    return "SNAPSHOT" in re.split(r"[.-]", suffix)


def core(version: str) -> tuple[int, int, int]:
    major, minor, patch, _, _ = VERSION.match(version).groups()
    return (int(major), int(minor), int(patch))


def successors(released: tuple[int, int, int]) -> list[tuple[int, int, int]]:
    """The three cores that may follow one, which is what SemVer permits and no more: one part goes up by one and
    everything to its right goes to zero."""
    major, minor, patch = released
    return [(major, minor, patch + 1), (major, minor + 1, 0), (major + 1, 0, 0)]


def as_text(version: tuple[int, int, int]) -> str:
    return "{}.{}.{}".format(*version)


def check_version(candidate: str, tags: list[str]) -> list[str]:
    """Whether `candidate` may be released, given every version already tagged."""

    if not VERSION.match(candidate):
        return [f"'{candidate}' is not a version this project releases"]
    if being_worked_on(candidate):
        return [f"{candidate} is a version being worked on, and a release is precisely what it cannot be"]

    released = sorted((tag for tag in tags if VERSION.match(tag)), key=precedence)
    if not released:
        return []  # Nothing to be consistent with; the first release may name itself anything valid.

    problems = []
    finals = [tag for tag in released if VERSION.match(tag).group(4) is None]
    is_final = VERSION.match(candidate).group(4) is None

    # The base invariant, and the one the rest rests on. An IDE offers an update by comparing versions, so a
    # release that does not outrank the last one is a release nobody is offered. "The last one" is the last one
    # offered to the same people: a final release goes to everyone and has to outrank the last final release,
    # not the pre-releases, which only their channel's subscribers ever see - so a stable hotfix 0.2.1 may go
    # out while 0.3.0-beta.1 is open, and nobody on either channel is offered a downgrade. A pre-release goes
    # to subscribers, who see everything, so it has to outrank the highest tag of all. The other side of that
    # coin: while a train is open, a hotfix can go out but not be tried on a channel first - 0.2.1-rc.1 sorts
    # below 0.3.0-beta.1 and is refused, where 0.2.1 itself passes.
    against = finals[-1] if is_final and finals else released[-1]
    if precedence(candidate) == precedence(against) and candidate != against:
        # Equal precedence and different text can only be build metadata, which the spec has ordering ignore.
        # Named apart from the refusal below, because "does not come after" reads as a mistake about a version
        # that plainly came after in time - what it does not do is outrank it, and nothing can be built on it.
        problems.append(
            f"{candidate} and {against} differ only in build metadata, which SemVer leaves out of ordering: "
            f"neither comes after the other, so whoever compares versions is offered no release at all"
        )
    elif precedence(candidate) <= precedence(against):
        problems.append(f"{candidate} does not come after {against}, which is released already")

    # The step is measured against the last *final* release rather than against the highest tag, so that a
    # pre-release train - 0.2.0-rc.1, 0.2.0-rc.2, 0.2.0 - stays inside one permitted core instead of every step
    # having to advance it. Going backwards inside that train is what the check above is for. It also means an
    # open train cannot be abandoned for a higher core: 0.4.0 does not follow 0.2.0, whatever 0.3.0-beta.1 says.
    # Where nothing final has been released there is no step to take, and the open train is the whole of what
    # may be worked towards: the way past 0.2.0-rc.1 is 0.2.0 and nothing else. Leaving this case unmeasured
    # would let a project that has only ever tagged pre-releases name any core at all.
    against, allowed = (finals[-1], successors(core(finals[-1]))) if finals else (released[-1], [core(released[-1])])
    if core(candidate) not in allowed:
        names = ", ".join(as_text(step) for step in allowed)
        one_of = "one of " if len(allowed) > 1 else ""
        problems.append(f"{candidate} does not follow {against}: the next version is {one_of}{names}")

    return problems


def next_worked_on(released: str) -> str:
    """The version to be worked on once `released` is out.

    A pre-release does not advance anything: `0.2.0-rc.1` was a step towards `0.2.0`, so work goes on heading
    for it. A final release is followed by the smallest claim that can be made about what comes next, a patch;
    whoever lands a feature raises it to a minor in the same pull request, where a reviewer can see the line.
    """
    major, minor, patch, suffix, _ = VERSION.match(released).groups()  # A build is released, not worked on.
    if suffix is not None:
        return f"{major}.{minor}.{patch}{SNAPSHOT}"
    return f"{major}.{minor}.{int(patch) + 1}{SNAPSHOT}"


def channel_of(version: str) -> str:
    """The distribution channel a version is published to: the first identifier of its pre-release suffix, or
    `default` for a final release. `0.3.0-beta.1` goes to `beta`, where only whoever subscribed to that channel
    is offered it; `0.3.0` goes to everyone. Identifiers are separated by dots and a hyphen is an ordinary
    character inside one, so `1.0.0-eap.2` names the channel `eap` while `1.0.0-eap-2`, equally valid, names
    `eap-2` - a channel per build, which is a thing to spell on purpose rather than to meet by accident.
    Build metadata is not part of it: `0.3.0-beta.1+sha.5114f85` still goes to `beta`, and `1.0.0+dfsg1`, which
    names no pre-release at all, goes to everyone. The JetBrains Marketplace and npm's dist-tags are two registries
    that work this way; a project publishing to one that does not gets `default` for everything.

    This is what a release is marked as a pre-release by, and what it is uploaded under. A project whose build
    also has to name the channel - because a publishing task of its own takes it - spells the rule a second
    time there, and the two then have to answer alike.
    """
    suffix = VERSION.match(version).group(4)
    if suffix is None:
        return "default"
    return suffix.split(".")[0]


def sections(changelog: str) -> dict[str, str]:
    """Each section of a changelog, by the version it names. The link definitions at the foot of the file are
    left out: they are rewritten on every release and belong to no one section."""

    text = LINK_DEFINITION.sub("", changelog)
    found = {}
    marks = list(SECTION.finditer(text))
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(text)
        found[mark.group(1)] = text[mark.end() : end].strip()
    return found


def check_changelog(head: str, released: dict[str, str], off_history: set[str] | None = None) -> list[str]:
    """Whether every section already released still reads the way the tag that released it says it does.

    `released` maps a version to CHANGELOG.md as it stood at that version's tag. A released section is a text
    that has been published - the release notes on GitHub, and whatever the registry shows as the notes for
    that version - so changing it afterwards makes the repository disagree with what readers were handed.

    `off_history` holds the versions whose tag this history does not reach, which `ancestry` is the check for.
    A section that is missing is read against it: between a release being published and its branch reaching the
    default branch, the section exists only where the tag does, and saying it is gone accuses somebody of
    deleting what nobody has written down here yet. Failing either way is right - the two are the same mess
    from two sides - but only one of them is a section somebody removed.
    """

    problems = []
    current = sections(head)
    off_history = off_history or set()

    for version, changelog in sorted(released.items(), key=lambda item: precedence(item[0])):
        was = sections(changelog).get(version)
        if was is None:
            continue  # Tagged before the section existed; there is nothing to have changed.
        if version not in current:
            if version in off_history:
                problems.append(
                    f"[{version}] is released but its section is not on this history: {version} is not on it "
                    f"either, so the release has yet to reach here"
                )
            else:
                problems.append(f"[{version}] is released but its section is gone")
        elif current[version] != was:
            problems.append(f"[{version}] is released but its section no longer reads as the tag has it")

    return problems


def unprotected(released: dict[str, str]) -> list[str]:
    """The released versions whose tag predates their section, so that check_changelog has nothing to hold them
    to. Named in the report rather than counted among the protected: a check that says it compared what it
    passed over is a check that passes having compared nothing, and nobody can tell from the outside."""
    return sorted((version for version, text in released.items() if version not in sections(text)), key=precedence)


def with_version(text: str, version: str) -> str:
    """gradle.properties with the version line rewritten and everything else left alone.

    A plain function over the text, like the rest of this file, so that what a release does to that line can be
    exercised without a repository - and so that the knowledge of how the line is written sits here, beside the
    reader of it, rather than in a pattern in a workflow that nothing tests. A replacement built by hand rather
    than by the regular expression's own substitution, because a version is data: `&` and `\\1` in it are
    characters, not instructions.

    A file declaring the version more than once is refused rather than rewritten at one of them. The reader
    takes the last declaration, as Gradle does, so rewriting any other leaves the version the build sees as
    it was - and rewriting the last one leaves a stale line above it for the next reader to trust.
    """
    replaced, count = VERSION_LINE.subn(lambda found: found.group(1) + version, text)
    if count == 0:
        raise SystemExit("gradle.properties names no version to rewrite")
    if count > 1:
        raise SystemExit(f"gradle.properties declares the version {count} times, and a release rewrites one "
                         f"declaration: say it once")
    return replaced


def check_ancestry(reachable: dict[str, bool], prefix: str, held_by: dict[str, str] | None = None) -> list[str]:
    """Whether every released tag is still part of the history it was released from.

    A tag points at the commit a release was built and signed from, and it is the only thing that still says
    what that was. Anything that rewrites the commits it sits among - a squash merge, a rebase merge, GitHub's
    `Update with rebase`, a force-push - leaves the tag pointing at a commit no branch reaches.

    Asking whether the tag is reachable answers that whatever the cause. Forbidding the causes one at a time
    does not: the list of ways to rewrite a branch is GitHub's to extend, not this project's.

    `held_by` names, for a tag that is not on this history, a branch that does still hold it. A release whose
    branch has not been carried back yet is exactly as unreleasable as one a rewrite orphaned, and is failed
    the same way - but it is a different thing to have happened and a different thing to do about it, so it is
    said differently. Blaming a rewrite for a merge that is merely outstanding sends the reader looking for
    damage that is not there.

    A branch holding the tag does not settle which of the two it was: a squash or a rebase merge replays the
    release commit and leaves the branch it came from standing, holding the original. Both readings are
    therefore named, because both are things the reader may be looking at and both are answered by looking at
    that one branch. Only a tag no branch holds at all is laid at a rewrite's door outright.
    """
    problems = []
    held_by = held_by or {}
    for version, found in sorted(reachable.items(), key=lambda item: precedence(item[0])):
        if found:
            continue
        branch = held_by.get(version)
        if branch:
            problems.append(
                f"{prefix}{version} is released but is not on this history: {branch} still holds it. Either "
                f"that branch has not been carried back yet, or it was landed with a squash or a rebase, "
                f"which replays the release commit and leaves the tag on the copy that was replaced"
            )
        else:
            problems.append(
                f"{prefix}{version} is released but is no longer reachable: a rewrite has taken it off this "
                f"history"
            )
    return problems


def git(*arguments: str) -> str:
    return subprocess.run(["git", *arguments], cwd=repository(), capture_output=True, text=True, check=True).stdout


def declared(name: str, holds: str, newline: str | None = None) -> str:
    """A file the repository declares something in, read as text - or a refusal that says which file is missing
    and what it is looked in for. A traceback is loud too, but it reads as the tool breaking rather than as the
    repository lacking something, and it names no remedy.

    `newline` is open()'s: left alone, line endings are read as `\\n`, and a writer that wants to put back the
    ones the file had asks for `""`."""
    try:
        with open(repository() / name, encoding="utf-8", newline=newline) as file:
            return file.read()
    except FileNotFoundError:
        raise SystemExit(f"there is no {name} here, and that is where {holds}") from None


def properties() -> dict[str, str]:
    """gradle.properties, read as the `name = value` lines a project declares its version in. Both spellings
    are taken, `version = 0.2.0` and `version=0.2.0`, because a reader that knows only one reports a file that
    names no version when it names one. Not the whole Java properties format - no `:` separator, no
    continuation lines, no escapes - which is enough for a version and a tag prefix and fails loudly rather
    than quietly when it is not."""
    found = {}
    for line in declared("gradle.properties", "the version and tagPrefix are declared").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "!")) or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        found[name.strip()] = value.strip()
    return found


def declared_version() -> str:
    """The version gradle.properties names, which is what a release is asked to be."""
    declared = properties().get("version")
    if declared is None:
        raise SystemExit("gradle.properties names no version")
    return declared


def tag_prefix() -> str:
    """What a release tag carries in front of its version - `v0.1.0` against `0.1.0`.

    Declared rather than assumed, and with no default, because both spellings are in use and the wrong guess is
    silent: a repository that tags bare versions, read as though it tagged `v*`, turns up no released tags at
    all, and every check over them then passes having compared nothing.
    """
    prefix = properties().get("tagPrefix")
    if prefix is None:
        raise SystemExit("gradle.properties does not say, in tagPrefix, what release tags are called")
    return prefix


def tags() -> list[str]:
    """Every tag that names a release, with the prefix off. The repository carries tags that are not releases
    - the backups a history rewrite left behind, and a version somebody tagged while it was still being worked
    on - and those are nothing to be consistent with."""
    prefix = tag_prefix()
    return [
        tag[len(prefix) :]
        for tag in git("tag", "-l", f"{prefix}*").split()
        if VERSION.match(tag[len(prefix) :]) and not being_worked_on(tag[len(prefix) :])
    ]


def version_command(arguments) -> list[str]:
    declared = arguments.version or declared_version()

    # Named rather than assumed: a report that says gradle.properties declares what was typed on the command
    # line sends its reader to edit a file that is not the one at fault.
    source = "--version" if arguments.version else "gradle.properties"

    # Work carries the marker and a release is what drops it. Reading the release version off the development
    # one, rather than being handed it, is what keeps the two from ever naming different things. It holds for
    # a version handed in too, which is why --version takes a declared one rather than a release.
    if not declared.endswith(SNAPSHOT):
        return [
            f"{source} names {declared}, which is not a version being worked on: "
            f"between releases it names the next one, marked {SNAPSHOT}"
        ]

    candidate = declared[: -len(SNAPSHOT)]
    problems = check_version(candidate, tags())
    if not problems:
        print(candidate)
    return problems


def changelog_command(arguments) -> list[str]:
    head = declared("CHANGELOG.md", "the released sections are")
    prefix = tag_prefix()

    released = {}
    for version in tags():
        try:
            released[version] = git("show", f"{prefix}{version}:CHANGELOG.md")
        except subprocess.CalledProcessError:
            continue  # Tagged before the file existed.

    problems = check_changelog(head, released, off_history=unreachable(prefix, released))
    if not problems:
        skipped = unprotected(released)
        print(f"Compared {len(released) - len(skipped)} released section(s) against the tag that released them.")
        if skipped:
            print(f"Not compared: {', '.join(skipped)} - tagged before the section existed, so the tag holds "
                  f"no text to compare against.")
    return problems


def next_command(arguments) -> list[str]:
    released = arguments.released.removeprefix(tag_prefix())
    if not VERSION.match(released):
        return [f"'{arguments.released}' is not a version this project releases"]
    print(next_worked_on(released))
    return []


def set_version_command(arguments) -> list[str]:
    """Write the version gradle.properties names, which is what a release does to it before it builds."""
    # Read and written with the line endings it has, so that a CRLF file is not rewritten whole to change one
    # line.
    path = repository() / "gradle.properties"
    written = with_version(declared(path.name, "the version is declared", newline=""), arguments.version)
    with open(path, "w", encoding="utf-8", newline="") as file:
        file.write(written)

    # Read back through the same reader everything else here uses. A rewrite that matched nothing is the failure
    # worth catching and it is the quiet one, which is the whole reason this is not a pattern in a shell script.
    if declared_version() != arguments.version:
        return [f"gradle.properties still does not name {arguments.version} after being rewritten"]
    print(arguments.version)
    return []


def channel_command(arguments) -> list[str]:
    version = arguments.version.removeprefix(tag_prefix())
    if not VERSION.match(version):
        return [f"'{arguments.version}' is not a version this project releases"]
    print(channel_of(version))
    return []


def prefix_command(arguments) -> list[str]:
    """What release tags are called here. Printed rather than written into the workflows, so that the spelling
    is declared once and a repository cannot come to disagree with its own tags."""
    print(tag_prefix())
    return []


def unreachable(prefix: str, versions) -> set[str]:
    """The released versions whose tag this history does not reach. Asked of Git in one place and handed to
    whichever check needs it, so that two checks looking at one repository cannot come to disagree about which
    releases are on it."""
    return {
        version
        for version in versions
        if subprocess.run(
            ["git", "merge-base", "--is-ancestor", f"{prefix}{version}", "HEAD"], cwd=repository(), capture_output=True
        ).returncode
        != 0
    }


def holder(tag: str, version: str) -> str:
    """A branch that still holds `tag`, or the empty string if none does.

    Asked only of a tag that HEAD does not reach, and only to tell one report apart from the other. Remote
    branches are asked first and named as they are fetched: a release is carried back from what the remote
    has, and a local branch of the same name may be something else entirely. The release branch is named
    ahead of anything else that happens to hold the tag, because it is the one the reader has to act on.
    """
    for pattern in ("refs/remotes", "refs/heads"):
        branches = git("for-each-ref", "--contains", tag, "--format=%(refname:short)", pattern).split()
        if branches:
            return sorted(branches, key=lambda name: (not name.endswith(f"release/{version}"), name))[0]
    return ""


def ancestry_command(arguments) -> list[str]:
    prefix = tag_prefix()
    released = tags()
    off_history = unreachable(prefix, released)
    reachable = {version: version not in off_history for version in released}

    held_by = {
        version: holder(f"{prefix}{version}", version) for version, found in reachable.items() if not found
    }
    problems = check_ancestry(reachable, prefix, held_by)
    if not problems:
        print(f"All {len(reachable)} released tag(s) are reachable from HEAD.")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(required=True)

    version = commands.add_parser("version", help="whether the declared version may be released next")
    version.add_argument("--version", help=f"check this instead of what gradle.properties says, marked "
                                            f"{SNAPSHOT} the way a declaration is")
    version.set_defaults(run=version_command)

    following = commands.add_parser("next", help="the version to be worked on once one is released")
    following.add_argument("released", help="the version just released, with or without the tag prefix")
    following.set_defaults(run=next_command)

    changelog = commands.add_parser("changelog", help="whether released sections still read as released")
    changelog.set_defaults(run=changelog_command)

    setting = commands.add_parser("set-version", help="write the version gradle.properties names")
    setting.add_argument("version", help="the version to write")
    setting.set_defaults(run=set_version_command)

    prefix = commands.add_parser("prefix", help="what release tags carry in front of the version")
    prefix.set_defaults(run=prefix_command)

    channel = commands.add_parser("channel", help="the distribution channel a version is published to")
    channel.add_argument("version", help="the version, with or without the tag prefix")
    channel.set_defaults(run=channel_command)

    ancestry = commands.add_parser("ancestry", help="whether every released tag is still reachable")
    ancestry.set_defaults(run=ancestry_command)

    arguments = parser.parse_args()
    problems = arguments.run(arguments)

    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
