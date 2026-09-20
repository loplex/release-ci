#!/usr/bin/env python3
"""What a release has to be true of, checked before and after it is one.

- `version` - whether the version the project declares may be released next, given the releases it already has tagged.
- `next` - the version to be worked on once one is released.
- `changelog` - whether every section already released still reads the way it was released.
- `ancestry` - whether every released tag is still reachable, a rewrite being able to take one off the history.
- `prefix` - what release tags are called here, so that the workflows do not have to say it a second time.
- `channel` - the distribution channel a version goes to, read off its pre-release suffix.
- `set-version` - write a version where the project declares it: the one released, then the next.

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
    taken from its own path would then name the wrong repository - quietly, because this one carries a
    CHANGELOG.md of its own for the checks to read instead. So the root is asked of git in the working
    directory, and nothing here assumes where the file sits.
    """
    rev_parse = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if rev_parse.returncode != 0:
        raise SystemExit("check-release.py has to be run inside the repository it is checking")
    return Path(rev_parse.stdout.strip())


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
PRE_RELEASE_IDENTIFIER = r"(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)"
BUILD_METADATA = r"(?:[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)"
SEMVER = re.compile(
    rf"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    rf"(?:-({PRE_RELEASE_IDENTIFIER}(?:\.{PRE_RELEASE_IDENTIFIER})*))?(?:\+({BUILD_METADATA}))?\Z",
    re.ASCII,
)

# The marker a version carries while it is being worked on. It is the one suffix never released to any channel:
# it says the version has not been released, so a release is precisely what it cannot be - check_version
# refuses a candidate still carrying it, and released_versions() leaves a tag carrying it out of what counts as
# released.
SNAPSHOT = "-SNAPSHOT"

# gradle.properties is a Java properties file, and Gradle reads it with java.util.Properties, so it is read here
# the way that class's load() documents: the version and the prefix a release takes are then the ones the build
# sees. A natural line ends at `\n`, `\r` or `\r\n`. One ending in an odd number of backslashes goes on in the next,
# whose leading white space is dropped, and `#` or `!` opens a comment only where a logical line starts. The key
# runs to the first `=`, `:` or white space that is not escaped; an escape is `\t`, `\n`, `\r`, `\f`, `\uXXXX`, or
# a backslash in front of any other character, which then stands for itself.
NATURAL_LINE = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+\Z")
KEY_AND_VALUE = re.compile(r"((?:\\.|[^\\=: \t\f])*)[ \t\f]*[=:]?[ \t\f]*(.*)", re.DOTALL)
ESCAPE = re.compile(r"\\(u[0-9A-Fa-f]{4}|u|.)", re.DOTALL)

# Gradle hands gradle.properties to Properties.load() as bytes, and that takes each byte for one Latin-1 character
# rather than decoding UTF-8. Read and written the same way, no byte in the file fails to decode, and a comment or
# any value but the version's, saved in any encoding, goes back in the bytes it was read from.
PROPERTIES_ENCODING = "iso-8859-1"

# What a release puts back in front of the version it writes: the indentation, the key and the separator exactly
# as the first line of the declaration has them. Gradle allows space around the separator and in front of the key,
# and projects write it every way, so it is put back rather than chosen here: turning one spelling into the other
# would show up in the diff as a change nobody made, and so would an indented declaration moved to the margin.
# Where a continuation splits the key itself, that first line holds only part of it, and the declaration is
# written again as `version = ` after that line's indentation.
DECLARATION_LEAD = re.compile(r"[ \t\f]*(?:\\[^\r\n]|[^\\=: \t\f\r\n])*[ \t\f]*[=:]?[ \t\f]*")

SECTION_HEADING = re.compile(r"^## \[([^\]]+)\]", re.MULTILINE)
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
    major, minor, patch, suffix, _ = SEMVER.match(version).groups()
    if suffix is None:
        return (int(major), int(minor), int(patch), 1, ())

    identifier_keys = tuple(
        (0, int(identifier), "") if identifier.isdigit() else (1, 0, identifier) for identifier in suffix.split(".")
    )
    return (int(major), int(minor), int(patch), 0, identifier_keys)


def being_worked_on(version: str) -> bool:
    """Whether `version` carries the SNAPSHOT marker as a dot- or hyphen-separated part of its pre-release suffix:
    `1.0.0-SNAPSHOT`, but also `1.0.0-rc.1-SNAPSHOT`, and `1.0.0-SNAPSHOT-SNAPSHOT`, which is what a script
    appending the marker to a version that already has it produces - and which the plain suffix strip in
    version_command turns into a candidate that still carries it. Split on both separators, so that `preSNAPSHOT`
    is not the marker and `rc.1-SNAPSHOT` is. Metadata is not looked at: it names a build, not a state."""
    suffix = SEMVER.match(version).group(4) or ""
    return "SNAPSHOT" in re.split(r"[.-]", suffix)


def core(version: str) -> tuple[int, int, int]:
    major, minor, patch, _, _ = SEMVER.match(version).groups()
    return (int(major), int(minor), int(patch))


def successors(released_core: tuple[int, int, int]) -> list[tuple[int, int, int]]:
    """The three cores that may follow one, which is what SemVer permits and no more: one part goes up by one and
    everything to its right goes to zero."""
    major, minor, patch = released_core
    return [(major, minor, patch + 1), (major, minor + 1, 0), (major + 1, 0, 0)]


def core_text(parts: tuple[int, int, int]) -> str:
    return "{}.{}.{}".format(*parts)


def check_version(candidate: str, releases: list[str]) -> list[str]:
    """Whether `candidate` may be released, given the releases already tagged."""

    if not SEMVER.match(candidate):
        return [f"'{candidate}' is not a version this project releases"]
    if being_worked_on(candidate):
        return [f"{candidate} is a version being worked on, and a release is precisely what it cannot be"]

    ordered = sorted((version for version in releases if SEMVER.match(version)), key=precedence)
    if not ordered:
        return []  # Nothing to be consistent with; the first release may name itself anything valid.

    problems = []
    finals = [version for version in ordered if SEMVER.match(version).group(4) is None]
    is_final = SEMVER.match(candidate).group(4) is None

    # The base invariant, and the one the rest rests on. An update check - an IDE's, a package manager's -
    # offers a release by comparing versions, so a release that does not outrank the last one is a release
    # nobody is offered. "The last one" is the last one offered to the same people: a final release goes to
    # everyone and has to outrank the last final release, not the pre-releases, which only their channel's
    # subscribers ever see - so a stable hotfix 0.2.1 may go out while 0.3.0-beta.1 is open, and nobody on
    # either channel is offered a downgrade. A pre-release goes to subscribers, who see everything, so it has
    # to outrank the highest tag of all. The other side of that coin: while a train is open, a hotfix can go
    # out but not be tried on a channel first - 0.2.1-rc.1 sorts below 0.3.0-beta.1 and is refused, where 0.2.1
    # itself passes.
    to_outrank = finals[-1] if is_final and finals else ordered[-1]
    if precedence(candidate) == precedence(to_outrank) and candidate != to_outrank:
        # Equal precedence and different text can only be build metadata, which the spec has ordering ignore.
        # Named apart from the refusal below, because "does not come after" reads as a mistake about a version
        # that plainly came after in time - what it does not do is outrank it, and nothing can be built on it.
        problems.append(
            f"{candidate} and {to_outrank} differ only in build metadata, which SemVer leaves out of ordering: "
            f"neither comes after the other, so whoever compares versions is offered no release at all"
        )
        # Nor is a step measured: a version differing from a release only in its metadata has that release's
        # core, and "does not follow" would be the very arithmetic this refusal is worded to keep out.
        return problems
    elif precedence(candidate) <= precedence(to_outrank):
        problems.append(f"{candidate} does not come after {to_outrank}, which is released already")

    # The step is measured against the last *final* release rather than against the highest tag, so that a
    # pre-release train - 0.2.0-rc.1, 0.2.0-rc.2, 0.2.0 - stays inside one permitted core instead of every step
    # having to advance it. Going backwards inside that train is what the check above is for. It also means an
    # open train cannot be left for a core the last final release does not permit: 0.4.0 does not follow 0.2.0,
    # whatever 0.3.0-beta.1 says, while 1.0.0 still does. Where nothing final has been released there is no step
    # to take, and the open train is the whole of what may be worked towards: past 0.2.0-rc.1 the way on stays
    # inside 0.2.0 - a later pre-release of it, or 0.2.0 itself. Leaving this case unmeasured would let a
    # project that has only ever tagged pre-releases name any core at all.
    if finals:
        measured_from, allowed = finals[-1], successors(core(finals[-1]))
    else:
        measured_from, allowed = ordered[-1], [core(ordered[-1])]
    if core(candidate) not in allowed:
        choices = ", ".join(core_text(permitted) for permitted in allowed)
        one_of = "one of " if len(allowed) > 1 else ""
        problems.append(f"{candidate} does not follow {measured_from}: the next version is {one_of}{choices}")

    return problems


def next_worked_on(released: str) -> str:
    """The version to be worked on once `released` is out.

    A pre-release does not advance anything: `0.2.0-rc.1` was a step towards `0.2.0`, so work goes on heading
    for it. A final release is followed by the smallest claim that can be made about what comes next, a patch;
    whoever lands a feature raises it to a minor in the same pull request, where a reviewer can see the line.
    """
    major, minor, patch, suffix, _ = SEMVER.match(released).groups()  # A build is released, not worked on.
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
    names no pre-release at all, goes to everyone. Channels on the JetBrains Marketplace and dist-tags on npm are
    what such a name is for. A registry with nothing of the kind is answered with the same channel, and what a
    pre-release suffix means there is for its publishing step to decide.

    Whatever marks a release as a pre-release, or uploads it under a channel, is meant to ask this rather than
    spell the rule again. A project whose build also has to name the channel - because a publishing task of
    its own takes it - spells the rule a second time there, and the two then have to answer alike.
    """
    suffix = SEMVER.match(version).group(4)
    if suffix is None:
        return "default"
    return suffix.split(".")[0]


def sections(changelog: str) -> dict[str, str]:
    """Each section of a changelog, by the label its heading carries - a version, or `Unreleased`. Link
    definitions are left out wherever they stand, so that one written inside a section is no part of what
    is compared either: the ones at the foot of the file belong to no one section, and are what a release
    may write afresh."""

    text = LINK_DEFINITION.sub("", changelog)
    found = {}
    marks = list(SECTION_HEADING.finditer(text))
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(text)
        found[mark.group(1)] = text[mark.end() : end].strip()
    return found


def check_changelog(in_tree: str, at_tag: dict[str, str], off_history: set[str] | None = None) -> list[str]:
    """Whether every section already released still reads the way the tag that released it says it does.

    `at_tag` maps a version to CHANGELOG.md as it stood at that version's tag. A released section is a text
    that has been published - the release notes on GitHub, and whatever the registry shows as the notes for
    that version - so changing it afterwards makes the repository disagree with what readers were handed.

    `off_history` holds the versions whose tag this history does not reach, which `ancestry` is the check for.
    A section that is missing is read against it: between a release being published and its branch reaching the
    default branch, the section exists only where the tag does, and saying it is gone accuses somebody of
    deleting what nobody has written down here yet. Failing either way is right - the two are the same mess
    from two sides - but only one of them is a section somebody removed.
    """

    problems = []
    current = sections(in_tree)
    off_history = off_history or set()

    for version, changelog in sorted(at_tag.items(), key=lambda item: precedence(item[0])):
        was = sections(changelog).get(version)
        if was is None:
            continue  # Tagged before the section existed; there is nothing to have changed.
        if version not in current:
            if version in off_history:
                problems.append(
                    f"[{version}] is released but its section is not on this history, and neither is the tag that "
                    f"released it: the release has yet to reach here"
                )
            else:
                problems.append(f"[{version}] is released but its section is gone")
        elif current[version] != was:
            problems.append(f"[{version}] is released but its section no longer reads as the tag has it")

    return problems


def uncompared(at_tag: dict[str, str]) -> list[str]:
    """The released versions whose tag predates their section, so that check_changelog has nothing to hold them
    to. Named in the report rather than counted among the compared: a check that says it compared what it
    passed over is a check that passes having compared nothing, and nobody can tell from the outside."""
    return sorted((version for version, text in at_tag.items() if version not in sections(text)), key=precedence)


def with_version(text: str, version: str) -> str:
    """gradle.properties with the version line rewritten and everything else left alone.

    A plain function over the text, like the rest of this file, so that what a release does to that line can be
    exercised without a repository - and so that the knowledge of how the line is written sits here, beside the
    reader of it, rather than in a pattern in a workflow that nothing tests. A replacement built by hand, the
    version written as data: `&` and `\\1` in it are characters, not instructions, and the version is escaped
    as Properties.store(OutputStream) escapes a value (see stored()), so that the file reads it back as it was
    given.

    A file declaring the version more than once is refused rather than rewritten at one of them. The reader
    takes the last declaration, as Gradle does, so rewriting any other leaves the version the build sees as
    it was - and rewriting the last one leaves a stale line above it for the next reader to trust.
    """
    declarations = [(start, end) for start, end, line in logical_lines(text)
                    if unescaped(KEY_AND_VALUE.match(line).group(1)) == "version"]
    if not declarations:
        raise SystemExit("gradle.properties names no version to rewrite")
    if len(declarations) > 1:
        raise SystemExit(f"gradle.properties declares the version {len(declarations)} times, and a release "
                         f"rewrites one declaration: say it once")
    start, end = declarations[0]
    lead = DECLARATION_LEAD.match(text, start).group(0)
    if unescaped(KEY_AND_VALUE.match(lead.lstrip(" \t\f")).group(1)) != "version":
        lead = lead[:len(lead) - len(lead.lstrip(" \t\f"))] + "version = "
    elif not lead.endswith(("=", ":", " ", "\t", "\f")):
        lead += " = "
    return text[:start] + lead + stored(version) + text[end:]


def check_ancestry(reachability: dict[str, bool], prefix: str, held_by: dict[str, str] | None = None) -> list[str]:
    """Whether every released tag is still part of the history it was released from.

    A tag points at the commit a release was made from, and it is the only thing that still says what that
    was. Anything that rewrites the commits it sits among - a squash merge, a rebase merge, GitHub's `Update
    with rebase`, a force-push - leaves the tag pointing at a commit this history no longer reaches.

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
    for version, reached in sorted(reachability.items(), key=lambda item: precedence(item[0])):
        if reached:
            continue
        branch = held_by.get(version)
        if branch:
            problems.append(
                f"{prefix}{version} is released but is not on this history: {branch} still holds it. Either "
                f"that branch has not been carried back yet, or it was landed with a squash or a rebase, "
                f"which replays the release commit and leaves the tag on the original the copy replaced"
            )
        else:
            problems.append(
                f"{prefix}{version} is released but is no longer reachable: a rewrite has taken it off this "
                f"history"
            )
    return problems


def git(*arguments: str) -> str:
    return subprocess.run(["git", *arguments], cwd=repository(), capture_output=True, text=True, check=True).stdout


def read_file(name: str, holds: str, encoding: str = "utf-8") -> str:
    """A file the repository declares something in, read as text - or a refusal that says which file is missing
    and what it is looked in for. A traceback is loud too, but it reads as the tool breaking rather than as the
    repository lacking something, and it names no remedy."""
    try:
        with open(repository() / name, encoding=encoding) as stream:
            return stream.read()
    except FileNotFoundError:
        raise SystemExit(f"there is no {name} here, and it is where {holds} would be read from") from None


def logical_lines(text: str) -> list[tuple[int, int, str]]:
    """Every logical line of a properties file that declares something, as (start, end, line): where its first
    natural line starts, where its last one ends, and the line with its continuations joined."""
    found, start, joined = [], 0, None
    for match in NATURAL_LINE.finditer(text):
        natural = match.group(0).rstrip("\r\n")
        body = natural.lstrip(" \t\f")
        if joined is None:
            if not body or body[0] in "#!":
                continue
            start, joined = match.start(), ""
        joined += body
        if (len(body) - len(body.rstrip("\\"))) % 2:
            joined = joined[:-1]
            continue
        found.append((start, match.start() + len(natural), joined))
        joined = None
    if joined is not None:
        found.append((start, len(text), joined))
    return found


def unescaped(text: str) -> str:
    """A key or a value with its escapes read. A `\\u` not followed by four hex digits is refused, as Properties
    refuses it, and two that make a UTF-16 surrogate pair are one character, as they are in the Java string
    Properties reads them into."""
    def one(escape):
        code = escape.group(1)
        if code == "u":
            raise SystemExit(f"gradle.properties has a malformed \\uxxxx escape in '{text}', which Gradle refuses "
                             "as well")
        escapes = {"t": "\t", "n": "\n", "r": "\r", "f": "\f"}
        return chr(int(code[1:], 16)) if len(code) == 5 else escapes.get(code, code)
    return ESCAPE.sub(one, text).encode("utf-16-le", "surrogatepass").decode("utf-16-le", "surrogatepass")


def stored(value: str) -> str:
    """A value written the way Properties.store(OutputStream) writes one, so that the file reads it back as it was given
    and no character of text fails to encode: a backslash doubled, a tab, a line break or a form feed as its escape, a
    leading space and `=`, `:`, `#`, `!` behind a backslash, and every other character below a space or above `~` as
    `\\uXXXX`, a character outside the first 65536 as the two of its UTF-16 pair. A lone surrogate is no character of
    text: it is what Python makes of a command-line byte its filesystem encoding cannot decode, and the UTF-16
    encoding below refuses it before the file is opened for writing. Properties.store(OutputStream) would write it as
    `\\uXXXX` instead."""
    escapes = {"\\": "\\\\", "\t": "\\t", "\n": "\\n", "\r": "\\r", "\f": "\\f"}
    written = []
    for at, character in enumerate(value):
        if character in escapes:
            written.append(escapes[character])
        elif character in "=:#!" or (character == " " and at == 0):
            written.append("\\" + character)
        elif not " " <= character <= "~":
            units = character.encode("utf-16-be")
            written.extend(f"\\u{int.from_bytes(units[i:i + 2], 'big'):04X}" for i in range(0, len(units), 2))
        else:
            written.append(character)
    return "".join(written)


def properties() -> dict[str, str]:
    """gradle.properties, every key it declares with its value, read the way Gradle reads them (see NATURAL_LINE):
    `version = 0.2.0`, `version=0.2.0` and `version: 0.2.0` alike, a line continued onto the next, an escape. A
    key declared twice keeps its last value, as it does for Gradle."""
    found = {}
    for _, _, line in logical_lines(read_file("gradle.properties", "the version and tagPrefix", PROPERTIES_ENCODING)):
        key, value = KEY_AND_VALUE.match(line).groups()
        found[unescaped(key)] = unescaped(value)
    return found


def declared_version() -> str:
    """The version gradle.properties names, `-SNAPSHOT` and all: what a release is asked to be once the marker is
    off."""
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


def released_versions() -> list[str]:
    """Every tag that names a release, with the prefix off. The repository carries tags that are not releases
    - another component's, a deployment's, a milestone's, and a version somebody tagged while it was still
    being worked on - and those are nothing to be consistent with."""
    prefix = tag_prefix()
    return [
        tag[len(prefix) :]
        for tag in git("tag", "-l", f"{prefix}*").split()
        if SEMVER.match(tag[len(prefix) :]) and not being_worked_on(tag[len(prefix) :])
    ]


def version_command(arguments) -> list[str]:
    named = arguments.version or declared_version()

    # Work carries the marker and a release is what drops it: the version released is the one worked on with
    # the marker taken off, so the two cannot come to name different things. Only a marker ending the version
    # comes off, and a version handed in may be spelled with it or without. One still carrying it after that -
    # `1.0.0-SNAPSHOT+b` - is refused by check_version as a version being worked on, which it is.
    candidate = named.removesuffix(SNAPSHOT)
    problems = check_version(candidate, released_versions())
    if not problems:
        print(candidate)
    return problems


def changelog_command(arguments) -> list[str]:
    in_tree = read_file("CHANGELOG.md", "the released sections")
    prefix = tag_prefix()

    at_tag = {}
    for version in released_versions():
        try:
            at_tag[version] = git("show", f"{prefix}{version}:CHANGELOG.md")
        except subprocess.CalledProcessError:
            # Tagged before the file existed, so there is no section to compare: reported below with the tags
            # older than their section.
            at_tag[version] = ""

    problems = check_changelog(in_tree, at_tag, off_history=unreachable(prefix, at_tag))
    if not problems:
        not_compared = uncompared(at_tag)
        print(f"Compared {len(at_tag) - len(not_compared)} released section(s) against the tag that released them.")
        if not_compared:
            print(f"Not compared: {', '.join(not_compared)} - tagged before the section existed, so the tag holds "
                  f"no text to compare against.")
    return problems


def next_command(arguments) -> list[str]:
    released = arguments.released.removeprefix(tag_prefix())
    if not SEMVER.match(released):
        return [f"'{arguments.released}' is not a version this project releases"]
    print(next_worked_on(released))
    return []


def set_version_command(arguments) -> list[str]:
    """Write a version into gradle.properties, which a release does twice: the version it releases, before it
    builds, and the next one being worked on, once it is out."""
    path = repository() / "gradle.properties"
    written = with_version(read_file(path.name, "the version", PROPERTIES_ENCODING), arguments.version)
    with open(path, "w", encoding=PROPERTIES_ENCODING) as stream:
        stream.write(written)

    # Read back through the same reader everything else here uses. What this catches is a writer and a reader
    # that have come to disagree - the quiet failure, and the whole reason this is not a pattern in a shell script.
    if declared_version() != arguments.version:
        return [f"gradle.properties still does not name {arguments.version} after being rewritten"]
    print(arguments.version)
    return []


def channel_command(arguments) -> list[str]:
    version = arguments.version.removeprefix(tag_prefix())
    if not SEMVER.match(version):
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
    has, and a local branch of the same name may be something else entirely. Among the branches of the kind
    that answered, one called `release/<version>` is named ahead of the rest, because it is the one the
    reader has to act on.
    """
    wanted = f"release/{version}"
    for pattern in ("refs/remotes", "refs/heads"):
        branches = git("for-each-ref", "--contains", tag, "--format=%(refname:short)", pattern).split()
        if branches:
            return sorted(branches, key=lambda name: (name != wanted and not name.endswith("/" + wanted), name))[0]
    return ""


def ancestry_command(arguments) -> list[str]:
    prefix = tag_prefix()
    releases = released_versions()
    off_history = unreachable(prefix, releases)
    reachability = {version: version not in off_history for version in releases}

    held_by = {
        version: holder(f"{prefix}{version}", version) for version, reached in reachability.items() if not reached
    }
    problems = check_ancestry(reachability, prefix, held_by)
    if not problems:
        print(f"All {len(releases)} released tag(s) are reachable from HEAD.")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(required=True)

    version_parser = commands.add_parser("version", help="whether the declared version may be released next")
    version_parser.add_argument("--version", help=f"check this instead of what gradle.properties says, with or "
                                            f"without the {SNAPSHOT} a declaration carries")
    version_parser.set_defaults(run=version_command)

    next_parser = commands.add_parser("next", help="the version to be worked on once one is released")
    next_parser.add_argument("released", help="the version just released, with or without the tag prefix")
    next_parser.set_defaults(run=next_command)

    changelog_parser = commands.add_parser("changelog", help="whether released sections still read as released")
    changelog_parser.set_defaults(run=changelog_command)

    set_version_parser = commands.add_parser("set-version", help="write a version into gradle.properties")
    set_version_parser.add_argument("version", help="the version to write")
    set_version_parser.set_defaults(run=set_version_command)

    prefix_parser = commands.add_parser("prefix", help="what release tags carry in front of the version")
    prefix_parser.set_defaults(run=prefix_command)

    channel_parser = commands.add_parser("channel", help="the distribution channel a version is published to")
    channel_parser.add_argument("version", help="the version, with or without the tag prefix")
    channel_parser.set_defaults(run=channel_command)

    ancestry_parser = commands.add_parser("ancestry", help="whether every released tag is still reachable")
    ancestry_parser.set_defaults(run=ancestry_command)

    arguments = parser.parse_args()
    problems = arguments.run(arguments)

    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
