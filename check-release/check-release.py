#!/usr/bin/env python3
"""What a release has to be true of, checked before and after it is one.

- `version` - whether the version the project declares may be released next, given the tags it already has.
- `next` - the version that follows a released one.
- `changelog` - whether every section already released still reads the way it was released.
- `ancestry` - whether every released tag is still reachable, a rewrite being able to take one off the history.
- `prefix` - what release tags are called here, so that the workflows do not have to say it a second time.
- `channel` - the distribution channel a version goes to, read off its pre-release suffix.
- `set-version` - write the version the project declares, which is what a release does.
- `close-changelog` - move what is under `[Unreleased]` into a section of its own, the other half of one.
- `section` - the text of one released section, which is what its release notes say.

All of it sits on plain functions over text, tags and booleans, so that the rules can be exercised without a
repository to release. The tests beside this file are what exercises them.
"""

import argparse
import datetime
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
# indentation is part of that and has to be, because gradle_properties() reads an indented line as a
# declaration - a writer that did not would refuse a file whose version it can see. The line ending is the
# same kind of thing: the value stops short of a carriage return, so a file written with CRLF keeps it.
GRADLE_VERSION_LINE = re.compile(r"^([ \t]*version[ \t]*=[ \t]*)([^\r\n]*)", re.MULTILINE)

SECTION = re.compile(r"^## \[([^\]]+)\]", re.MULTILINE)
UNRELEASED = re.compile(r"^## \[Unreleased\][^\n]*\n", re.MULTILINE)
GROUP = re.compile(r"^### (.+?)[ \t]*$", re.MULTILINE)

# The kinds of change Keep a Changelog names, in the order it names them - which is the order a section put
# together from several is written in. A group of any other name keeps the place it was first met in, after
# these, rather than being dropped: the text under it was released too.
KINDS = ("Added", "Changed", "Deprecated", "Removed", "Fixed", "Security")
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


def version_after(released: str) -> str:
    """The version that follows `released`, carrying no marker: what a project declaring its version writes
    back as the next one being worked on, and what a repository versioned by its tags alone offers as the
    default when a release is asked for. The marker, where there is one, is the source's to add.

    A pre-release does not advance anything: `0.2.0-rc.1` was a step towards `0.2.0`, so work goes on heading
    for it. A final release is followed by the smallest claim that can be made about what comes next, a patch;
    whoever lands a feature raises it to a minor in the same pull request, where a reviewer can see the line.
    """
    major, minor, patch, suffix, _ = VERSION.match(released).groups()  # A build is released, not worked on.
    if suffix is not None:
        return f"{major}.{minor}.{patch}"
    return f"{major}.{minor}.{int(patch) + 1}"


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


def bodies(changelog: str) -> dict[str, str]:
    """Each section's text below its heading line, by the version it names. What sections() holds without the
    rest of the heading - the date - which here would read as the first entry. Link definitions left out, as
    there."""
    text = LINK_DEFINITION.sub("", changelog)
    marks = list(SECTION.finditer(text))
    found = {}
    for index, mark in enumerate(marks):
        start = text.find("\n", mark.end())
        start = len(text) if start < 0 else start + 1
        end = marks[index + 1].start() if index + 1 < len(marks) else len(text)
        found[mark.group(1)] = text[start:end].strip("\n")
    return found


def combined(texts: list[str]) -> str:
    """Several sections' text as one: whatever stands before a first `###` kept at the top, and each group's
    entries together under one heading of its name, in the order the texts come in."""
    leads, merged = [], {}
    for text in texts:
        marks = list(GROUP.finditer(text))
        lead = (text[: marks[0].start()] if marks else text).strip("\n")
        if lead:
            leads.append(lead)
        for index, mark in enumerate(marks):
            end = marks[index + 1].start() if index + 1 < len(marks) else len(text)
            entries = text[mark.end() : end].strip("\n")
            if entries:
                merged.setdefault(mark.group(1), []).append(entries)
    order = [kind for kind in KINDS if kind in merged] + [name for name in merged if name not in KINDS]
    return "\n\n".join(leads + [f"### {name}\n\n" + "\n".join(merged[name]) for name in order])


def linked(changelog: str, repository: str, prefix: str) -> str:
    """The changelog with its link definitions written afresh, the way the Gradle changelog plugin writes them:
    [Unreleased] compared from the newest release to HEAD, each release compared from the one below it in the
    file, and the oldest pointing at its own commits. Rewritten whole rather than added to, because every
    release moves the first of them - which is also why check_changelog leaves them out."""
    versions = [version for version in sections(changelog) if version != "Unreleased"]
    lines = []
    if versions:
        lines.append(f"[Unreleased]: {repository}/compare/{prefix}{versions[0]}...HEAD")
    for index, version in enumerate(versions):
        below = versions[index + 1] if index + 1 < len(versions) else None
        target = f"compare/{prefix}{below}...{prefix}{version}" if below else f"commits/{prefix}{version}"
        lines.append(f"[{version}]: {repository}/{target}")
    text = LINK_DEFINITION.sub("", changelog).rstrip("\n")
    return text + ("\n\n" + "\n".join(lines) if lines else "") + "\n"


def closed(changelog: str, version: str, on: str, repository: str | None = None, prefix: str = "") -> str:
    """The changelog with everything under `[Unreleased]` moved into a section of its own, dated `on`.

    What a release does to the file before it is one, and the counterpart of check_changelog: the section this
    writes is the section that may never be edited again, because the tag is about to hold a copy of it.

    Two things are refused rather than written. A version that already has a section means this has run twice,
    or that a section was written by hand, and closing again would bury one of them. An empty `[Unreleased]`
    means a release with nothing to say about itself, and that emptiness would be compared against ever after.

    Link definitions at the foot of the file belong to the file rather than to the section being closed, so
    they stay where they are. Both shapes are in use - a changelog carrying them, and one that does not. Given
    the repository, they are written afresh instead, the way the Gradle changelog plugin writes them.

    A final release closing a pre-release train takes the train's entries into its own section, which is what
    the Gradle changelog plugin's `combinePreReleases` does and has on by default: whoever skipped the betas is
    told in one place everything 0.3.0 brings. The pre-release sections stay as they were, released and held to
    their tags. Emptiness is then judged on the section that results, so a train with nothing new to say at
    its end still closes. Only a final release does this. The plugin's own code does not check for it and
    would let 0.3.0-beta.2 take in 0.3.0-beta.1 as well, repeating to a channel what it was already offered;
    its documentation speaks of the final release, and so does this.
    """
    mark = UNRELEASED.search(changelog)
    if mark is None:
        raise SystemExit("CHANGELOG.md has no [Unreleased] section, so there is nothing to close")
    if version in sections(changelog):
        raise SystemExit(f"CHANGELOG.md already has a section for {version}")

    rest = changelog[mark.end() :]
    following = SECTION.search(rest)
    pending, after = (rest[: following.start()], rest[following.start() :]) if following else (rest, "")

    lines = pending.split("\n")
    foot = []
    while lines and (not lines[-1].strip() or LINK_DEFINITION.fullmatch(lines[-1])):
        foot.insert(0, lines.pop())

    entries = "\n".join(lines).strip("\n")
    shape = VERSION.match(version)
    if shape and shape.group(4) is None:
        train = [
            text for released, text in bodies(changelog).items()
            if VERSION.match(released) and VERSION.match(released).group(4) is not None
            and core(released) == core(version)
        ]
        if train:
            entries = combined([entries, *train])
    if not entries:
        raise SystemExit("nothing is under [Unreleased], and no pre-release of it to take in, so there is "
                         "nothing to release")

    # The blank line before whatever follows is put back rather than inherited: the run of blank lines that
    # separated [Unreleased] from the section below it was just taken off the end of the entries.
    tail = "\n".join(foot).strip("\n")
    body = f"\n## [{version}] - {on}\n\n{entries}\n"
    if tail:
        body += f"\n{tail}\n"
    if after:
        body += "\n"
    written = changelog[: mark.end()] + body + after
    return linked(written, repository.rstrip("/"), prefix) if repository else written


def gradle_with_version(text: str, version: str) -> str:
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
    replaced, count = GRADLE_VERSION_LINE.subn(lambda found: found.group(1) + version, text)
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


def gradle_properties() -> dict[str, str]:
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


def gradle_declared_version() -> str:
    """The version gradle.properties names, which is what a release is asked to be."""
    declared = gradle_properties().get("version")
    if declared is None:
        raise SystemExit("gradle.properties names no version")
    return declared


# Where the version a release is asked to be comes from, and what is recorded once it is one. This is the one
# thing here that a project type decides, and the two halves are not the same question. A Gradle project
# declares the next version in a file and carries a marker on it while it is being worked on, so a release
# reads the version off that file and writes the following one back. A repository consumed by tag alone
# declares nothing: it is handed the version when a release is asked for, and records nothing afterwards,
# because there is no file to record it in.
#
# Another source - package.json, pyproject.toml, Cargo.toml, a plain VERSION file - is a branch in the three
# functions below, and a reader and a writer of its file beside gradle_declared_version and gradle_with_version.
# version_command and set_version_command call those two outright, Gradle's being the one source that declares
# a version, so a second one is also where they come to choose. The three sit together and are named for it so
# that the boundary is a place in this file rather than a habit.
SOURCES = ("gradle.properties", "tags")


def declares_a_version(source: str) -> bool:
    """Whether the source names the version between releases, so that a release reads it rather than being
    handed it. Where it does, a release writes the next one back afterwards; where it does not, `set-version`
    has nothing to write to and says so rather than reporting a success nothing happened in."""
    return source != "tags"


def marker_of(source: str) -> str:
    """The suffix a version carries while it is being worked on, or the empty string where the source has no
    such state. `-SNAPSHOT` is Gradle's and Maven's spelling and not a rule of releasing: a repository whose
    version lives only in its tags has no version being worked on for a marker to sit on."""
    return SNAPSHOT if source == "gradle.properties" else ""


def prefix_from(source: str, given: str | None) -> str:
    """What a release tag carries in front of its version - `v0.1.0` against `0.1.0`.

    Declared rather than assumed, and with no default here, because both spellings are in use and the wrong
    guess is silent: a repository that tags bare versions, read as though it tagged `v*`, turns up no released
    tags at all, and every check over them then passes having compared nothing. A caller that wants a default
    declares it where its own readers can see it, rather than having this file guess on everyone's behalf.
    """
    if given is not None:
        return given
    if source == "gradle.properties":
        prefix = gradle_properties().get("tagPrefix")
        if prefix is None:
            raise SystemExit("gradle.properties does not say, in tagPrefix, what release tags are called")
        return prefix
    raise SystemExit(f"--tag-prefix says what release tags are called, which {source} does not declare")


def next_candidate(prefix: str) -> str:
    """The version to release when nobody says which: the one following the highest release there is.

    What a dispatch offers as its default, a form being unable to compute one - the field is left empty and
    this answers it. With nothing released there is nothing to count from, and the first version is named
    outright rather than guessed at.
    """
    released = tags(prefix)
    if not released:
        raise SystemExit("nothing is released here to count from, so say which version to release")
    return version_after(sorted(released, key=precedence)[-1])


def tags(prefix: str) -> list[str]:
    """Every tag that names a release, with the prefix off. The repository carries tags that are not releases
    - the backups a history rewrite left behind, and a version somebody tagged while it was still being worked
    on - and those are nothing to be consistent with.

    Counting none out of many is said out loud rather than returned quietly. It is not a failure: a repository
    may hold nothing but backups, and a first release has nothing to be consistent with either. But it is also
    exactly what a prefix nobody checked looks like, and every check over the result then passes having
    compared nothing - the one outcome worth fearing here, being the one nobody is told about.

    Selected by what the tag starts with rather than by a glob, so that the count of what was passed over is
    had in the same breath as the selection, and so that a prefix is read as text rather than as a pattern.
    """
    every = git("tag", "-l").split()
    releases = [
        tag[len(prefix) :]
        for tag in every
        if tag.startswith(prefix)
        and VERSION.match(tag[len(prefix) :])
        and not being_worked_on(tag[len(prefix) :])
    ]
    if every and not releases:
        called = f"the prefix '{prefix}'" if prefix else "no prefix at all"
        print(f"note: this repository has {len(every)} tag(s) and none of them is a release under {called}, "
              f"so every check over releases is about to compare nothing", file=sys.stderr)
    return releases


def version_command(arguments) -> list[str]:
    prefix = prefix_from(arguments.source, arguments.tag_prefix)

    if declares_a_version(arguments.source):
        declared = arguments.version or gradle_declared_version()
        marker = marker_of(arguments.source)

        # Named rather than assumed: a report that says the file declares what was typed on the command line
        # sends its reader to edit something that is not at fault.
        named = "--version" if arguments.version else arguments.source

        # Work carries the marker and a release is what drops it. Reading the release version off the
        # development one, rather than being handed it, is what keeps the two from ever naming different
        # things. It holds for a version handed in too, which is why --version takes a declared one.
        if marker and not declared.endswith(marker):
            return [
                f"{named} names {declared}, which is not a version being worked on: "
                f"between releases it names the next one, marked {marker}"
            ]
        candidate = declared.removesuffix(marker)
    else:
        # Handed in, or the default a dispatch leaves empty. Nothing is read and nothing will be written.
        candidate = arguments.version or next_candidate(prefix)

    problems = check_version(candidate, tags(prefix))
    if not problems:
        print(candidate)
    return problems


def changelog_command(arguments) -> list[str]:
    head = declared("CHANGELOG.md", "the released sections are")
    prefix = prefix_from(arguments.source, arguments.tag_prefix)

    released = {}
    for version in tags(prefix):
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
    released = arguments.released.removeprefix(prefix_from(arguments.source, arguments.tag_prefix))
    if not VERSION.match(released):
        return [f"'{arguments.released}' is not a version this project releases"]
    print(version_after(released) + marker_of(arguments.source))
    return []


# The exit status of `set-version` under a source that declares no version, apart from the 1 every other
# refusal gives. A caller carrying on without writing has to tell "there is nothing to write to" from "the
# write failed", and only the first is safe to carry on from.
NOTHING_TO_WRITE = 3


def set_version_command(arguments) -> list[str]:
    """Write the version the source declares, which is what a release does to it before it builds."""
    if not declares_a_version(arguments.source):
        print(f"{arguments.source} declares no version, so there is nothing here to write one to",
              file=sys.stderr)
        raise SystemExit(NOTHING_TO_WRITE)

    # Read and written with the line endings it has, so that a CRLF file is not rewritten whole to change one
    # line.
    path = repository() / arguments.source
    written = gradle_with_version(declared(path.name, "the version is declared", newline=""), arguments.version)
    with open(path, "w", encoding="utf-8", newline="") as file:
        file.write(written)

    # Read back through the same reader everything else here uses. A rewrite that matched nothing is the failure
    # worth catching and it is the quiet one, which is the whole reason this is not a pattern in a shell script.
    if gradle_declared_version() != arguments.version:
        return [f"{arguments.source} still does not name {arguments.version} after being rewritten"]
    print(arguments.version)
    return []


def close_changelog_command(arguments) -> list[str]:
    """Close [Unreleased] into a section for the version being released, which is what a release does to the
    file before it is one."""
    path = repository() / "CHANGELOG.md"
    on = arguments.date or datetime.date.today().isoformat()
    # Asked for only where links are to be written: a changelog without them has no use for the prefix, and a
    # source that declares none should not have to be told one just to close a section.
    prefix = prefix_from(arguments.source, arguments.tag_prefix) if arguments.repository_url else ""
    # Written back with the line endings it has, for the reason set_version_command gives: the release commit
    # should add one section, not rewrite every line of the file. closed() works over LF text either way.
    raw = declared("CHANGELOG.md", "the released sections are", newline="")
    ending = "\r\n" if "\r\n" in raw else "\n"
    text = raw.replace("\r\n", "\n")
    # Closed before the file is opened: opening it for writing empties it, and a refusal raised in between would
    # leave no changelog at all where the one it had should stand.
    written = closed(text, arguments.version, on, arguments.repository_url, prefix)
    with open(path, "w", encoding="utf-8", newline=ending) as file:
        file.write(written)
    print(f"[{arguments.version}] - {on}")
    return []


def section_command(arguments) -> list[str]:
    """The text of one released section, below its heading: what the release notes say. Taken from the same
    file the changelog check holds to the tag, so the release page and the changelog cannot come to say
    different things - and refused where there is nothing to say, a release whose notes are empty being one
    nobody meant to make."""
    text = bodies(declared("CHANGELOG.md", "the released sections are")).get(arguments.version, "")
    if not text.strip():
        return [f"CHANGELOG.md holds nothing for {arguments.version}, so there are no notes to release it with"]
    print(text)
    return []


def channel_command(arguments) -> list[str]:
    version = arguments.version.removeprefix(prefix_from(arguments.source, arguments.tag_prefix))
    if not VERSION.match(version):
        return [f"'{arguments.version}' is not a version this project releases"]
    print(channel_of(version))
    return []


def prefix_command(arguments) -> list[str]:
    """What release tags are called here. Printed rather than written into the workflows, so that the spelling
    is declared once and a repository cannot come to disagree with its own tags."""
    print(prefix_from(arguments.source, arguments.tag_prefix))
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
    prefix = prefix_from(arguments.source, arguments.tag_prefix)
    released = tags(prefix)
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
    parser.add_argument("--source", required=True, choices=SOURCES,
                        help="where the version a release is asked to be comes from")
    parser.add_argument("--tag-prefix", help="what release tags carry in front of the version, for a source "
                                             "that declares no prefix of its own")
    commands = parser.add_subparsers(required=True)

    version = commands.add_parser("version", help="whether the declared version may be released next")
    version.add_argument("--version", help="release this version: the one to check instead of what the "
                                           "source declares, marked the way that source marks a declaration")
    version.set_defaults(run=version_command)

    following = commands.add_parser("next", help="the version that follows a released one")
    following.add_argument("released", help="the version just released, with or without the tag prefix")
    following.set_defaults(run=next_command)

    changelog = commands.add_parser("changelog", help="whether released sections still read as released")
    changelog.set_defaults(run=changelog_command)

    setting = commands.add_parser("set-version", help="write the version the source declares")
    setting.add_argument("version", help="the version to write")
    setting.set_defaults(run=set_version_command)

    closing = commands.add_parser("close-changelog", help="close [Unreleased] into a released section")
    closing.add_argument("version", help="the version being released")
    closing.add_argument("--date", help="the date to give the section, today by default")
    closing.add_argument("--repository-url", help="write the link definitions afresh, pointing into this "
                                                  "repository; left alone without it")
    closing.set_defaults(run=close_changelog_command)

    showing = commands.add_parser("section", help="the text of one released section, as release notes")
    showing.add_argument("version", help="the version whose section to print")
    showing.set_defaults(run=section_command)

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
