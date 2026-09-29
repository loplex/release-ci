#!/usr/bin/env python3
"""What a release has to be true of, checked before and after it is one.

- `version` - whether the candidate version may be released next, given the releases already tagged.
- `next` - the version that follows a released one, carrying the source's marker.
- `changelog` - whether every section already released still reads the way it was released.
- `ancestry` - whether every released tag is still reachable, a rewrite being able to take one off the history.
- `prefix` - what release tags are called here, read from the source where it declares the prefix, so that
  the workflows do not have to say it a second time.
- `channel` - the distribution channel a version goes to, read off its pre-release suffix.
- `set-version` - write a version where the project declares it: the one released, then the next.
- `close-changelog` - move what is under `[Unreleased]` into a section of its own, the other half of what a
  release writes.
- `notes` - the text below one released section's heading, which is what its release notes say.

All of it sits on plain functions over text, tags and booleans, so that the rules can be exercised without a
repository to release. The tests beside this file are what exercises them.
"""

import argparse
import datetime
import re
import subprocess
import sys
from pathlib import Path

import sources


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

SECTION_HEADING = re.compile(r"^## \[([^\]]+)\]", re.MULTILINE)
UNRELEASED_HEADING = re.compile(r"^## \[Unreleased\][^\n]*\n", re.MULTILINE)
GROUP_HEADING = re.compile(r"^### (.+?)[ \t]*$", re.MULTILINE)

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


def version_after(released: str) -> str:
    """The version that follows `released`, carrying no marker: what a project declaring its version writes
    back as the next one being worked on, and what a repository versioned by its tags alone offers as the
    default when a release is asked for. The marker, where there is one, is the source's to add.

    A pre-release does not advance anything: `0.2.0-rc.1` was a step towards `0.2.0`, so work goes on heading
    for it. A final release is followed by the smallest claim that can be made about what comes next, a patch;
    where the source declares a version, whoever lands a feature raises it to a minor in the same pull
    request, where a reviewer can see the line, and where it declares none, whoever asks for the release names
    the minor.
    """
    major, minor, patch, suffix, _ = SEMVER.match(released).groups()  # Metadata names a build, not what follows it.
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


def bodies(changelog: str) -> dict[str, str]:
    """Each section's text below its heading line, by the label its heading carries. What sections() holds
    without the rest of the heading - the date - which here would read as the first entry. Link definitions
    left out, as there."""
    text = LINK_DEFINITION.sub("", changelog)
    marks = list(SECTION_HEADING.finditer(text))
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
        marks = list(GROUP_HEADING.finditer(text))
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


def linked(changelog: str, repository_url: str, prefix: str) -> str:
    """The changelog with its link definitions written afresh, the way the Gradle changelog plugin writes them:
    [Unreleased] compared from the newest release to HEAD, each release compared from the one below it in the
    file, and the oldest pointing at its own commits. Rewritten whole rather than added to, because every
    release moves the first of them - which is also why check_changelog leaves them out. Only the definitions
    written here are replaced: one the changelog keeps for a link of its own, to Keep a Changelog say, is
    left where it stands."""
    versions = [version for version in sections(changelog) if version != "Unreleased"]
    definitions = []
    if versions:
        definitions.append(f"[Unreleased]: {repository_url}/compare/{prefix}{versions[0]}...HEAD")
    for index, version in enumerate(versions):
        below = versions[index + 1] if index + 1 < len(versions) else None
        target = f"compare/{prefix}{below}...{prefix}{version}" if below else f"commits/{prefix}{version}"
        definitions.append(f"[{version}]: {repository_url}/{target}")
    labels = {"Unreleased", *versions}
    kept = [line for line in changelog.split("\n")
            if not (LINK_DEFINITION.fullmatch(line) and line[1 : line.index("]")] in labels)]
    text = "\n".join(kept).rstrip("\n")
    return text + ("\n\n" + "\n".join(definitions) if definitions else "") + "\n"


def closed(changelog: str, version: str, on: str, repository_url: str | None = None, prefix: str = "") -> str:
    """The changelog with everything under `[Unreleased]` moved into a section of its own, dated `on`.

    What a release does to the file before it is one, and the counterpart of check_changelog: the section this
    writes is the section that may never be edited again, because the tag is about to hold a copy of it.

    Three things are refused rather than written. A file with no `[Unreleased]` section has nothing to close.
    A version that already has a section means this has run twice, or that a section was written by hand, and
    closing again would bury one of them. An empty `[Unreleased]` means a release with nothing to say about
    itself, and that emptiness would be compared against ever after.

    Link definitions at the foot of the file belong to the file rather than to the section being closed, so
    they stay where they are. Both shapes are in use - a changelog carrying them, and one that does not. Given
    the repository's URL, they are written afresh instead, the way the Gradle changelog plugin writes them.

    A final release closing a pre-release train takes the train's entries into its own section, which is what
    the Gradle changelog plugin's `combinePreReleases` does and has on by default: whoever skipped the betas is
    told in one place everything 0.3.0 brings. The pre-release sections stay as they were, released and held to
    their tags. Emptiness is then judged on the section that results, so a train with nothing new to say at
    its end still closes. Only a final release does this. The plugin's own code does not check for it and
    would let 0.3.0-beta.2 take in 0.3.0-beta.1 as well, repeating to a channel what it was already offered;
    its documentation speaks of the final release, and so does this.
    """
    mark = UNRELEASED_HEADING.search(changelog)
    if mark is None:
        raise SystemExit("CHANGELOG.md has no [Unreleased] section, so there is nothing to close")
    if version in sections(changelog):
        raise SystemExit(f"CHANGELOG.md already has a section for {version}")

    rest = changelog[mark.end() :]
    following = SECTION_HEADING.search(rest)
    pending, after = (rest[: following.start()], rest[following.start() :]) if following else (rest, "")

    lines = pending.split("\n")
    foot_lines = []
    while lines and (not lines[-1].strip() or LINK_DEFINITION.fullmatch(lines[-1])):
        foot_lines.insert(0, lines.pop())

    entries = "\n".join(lines).strip("\n")
    is_final = SEMVER.match(version) is not None and SEMVER.match(version).group(4) is None
    if is_final:
        train_entries = [
            text for label, text in bodies(changelog).items()
            if SEMVER.match(label) and SEMVER.match(label).group(4) is not None
            and core(label) == core(version)
        ]
        if train_entries:
            entries = combined([entries, *train_entries])
    if not entries:
        raise SystemExit("nothing is under [Unreleased], and no pre-release of it to take in, so there is "
                         "nothing to release")

    # The blank line before whatever follows is put back rather than inherited: the run of blank lines that
    # separated [Unreleased] from the section below it was just taken off the end of the entries.
    foot = "\n".join(foot_lines).strip("\n")
    replacement = f"\n## [{version}] - {on}\n\n{entries}\n"
    if foot:
        replacement += f"\n{foot}\n"
    if after:
        replacement += "\n"
    written = changelog[: mark.end()] + replacement + after
    return linked(written, repository_url.rstrip("/"), prefix) if repository_url else written


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


def read_declared(adapter) -> str:
    """The file an adapter declares its version in, read in the encoding its format is read in."""
    return read_file(adapter.file, adapter.holds, adapter.encoding)


# Where the version a release is asked to be comes from is the one thing here that a project type decides, and
# it is decided in sources.py, one adapter per kind of repository. The four functions below are what the rules
# ask of one - whether it declares a version, the marker it carries while one is being worked on, the version it
# names, the tag prefix - and set_version_command hands it the text to rewrite. Reading and writing the file an
# adapter names is done here, both in the adapter's `encoding`, and the reading by read_declared() with the
# adapter's `holds` saying what the file is looked in for, so that a missing file is refused the same way
# whatever the format. The whole of what an adapter answers is listed at the top of sources.py.
SOURCES = sources.SOURCES


def declares_a_version(source: str) -> bool:
    """Whether the source names the version between releases, so that a release reads it rather than being
    handed it. Where it does, a release writes the next one back afterwards; where it does not, `set-version`
    has nothing to write to and says so rather than reporting a success nothing happened in."""
    return SOURCES[source].declares_a_version


def marker_of(source: str) -> str:
    """The ending a version carries while it is being worked on, hyphen and all - `-SNAPSHOT` for
    gradle.properties - or the empty string where the source has no such state: a repository whose version
    lives only in its tags has no version being worked on for a marker to sit on."""
    return SOURCES[source].marker


def declared_version(source: str) -> str:
    """The version a source that declares one names, marker and all: what a release is asked to be once the
    marker is off."""
    adapter = SOURCES[source]
    return adapter.version(read_declared(adapter))


def prefix_from(source: str, given: str | None) -> str:
    """What a release tag carries in front of its version - `v0.1.0` against `0.1.0`.

    Declared rather than assumed, and with no default here, because both spellings are in use and the wrong
    guess passes: a repository that tags bare versions, read as though it tagged `v*`, turns up no released
    tags at all, and every check over them - all but `version` under `tags` given no version, which finds no
    release to count from - then passes having compared nothing, with no more than a note on stderr to say
    so. A caller that wants a default declares it where its own readers can see it, rather than having this
    file guess on everyone's behalf.
    """
    if given is not None:
        return given
    adapter = SOURCES[source]
    if adapter.file is not None:
        return adapter.tag_prefix(read_declared(adapter))
    raise SystemExit(f"--tag-prefix says what release tags are called, which {source} does not declare")


def next_candidate(prefix: str) -> str:
    """The version to release when nobody says which: the one following the highest release there is.

    A dispatch form cannot compute a default, so its field is left empty and this answers it. With nothing
    released there is nothing to count from, and the first version is named outright rather than guessed at.
    """
    releases = released_versions(prefix)
    if not releases:
        raise SystemExit("nothing is released here to count from, so say which version to release")
    return version_after(sorted(releases, key=precedence)[-1])


def released_versions(prefix: str) -> list[str]:
    """Every tag that names a release, with the prefix off. The repository carries tags that are not releases
    - another component's, a deployment's, a milestone's, and a version somebody tagged while it was still
    being worked on - and those are nothing to be consistent with.

    Counting none out of many is said out loud rather than returned quietly. It is not a failure: a repository
    may carry tags of other kinds only, and a first release has nothing to be consistent with either. But it is
    also exactly what a prefix nobody checked looks like, and every check over the result then passes having
    compared nothing, the one outcome worth fearing here. Only `version` under `tags`, given no version, fails
    instead, finding no release to count from.

    Selected by what the tag starts with rather than by a glob, so that the count of what was passed over is
    had in the same breath as the selection, and so that a prefix is read as text rather than as a pattern.
    """
    tags = git("tag", "-l").split()
    releases = [
        tag[len(prefix) :]
        for tag in tags
        if tag.startswith(prefix)
        and SEMVER.match(tag[len(prefix) :])
        and not being_worked_on(tag[len(prefix) :])
    ]
    if tags and not releases:
        called = f"the prefix '{prefix}'" if prefix else "no prefix at all"
        print(f"note: this repository has {len(tags)} tag(s) and none of them is a release under {called}, "
              f"so there is no release to compare against", file=sys.stderr)
    return releases


def version_command(arguments) -> list[str]:
    prefix = prefix_from(arguments.source, arguments.tag_prefix)

    if declares_a_version(arguments.source):
        named = arguments.version or declared_version(arguments.source)

        # Work carries the marker and a release is what drops it: the version released is the one worked on
        # with the marker taken off, so the two cannot come to name different things. Only a marker ending the
        # version comes off, and a version handed in may be spelled with it or without. One still carrying it
        # after that - `1.0.0-SNAPSHOT+b` - is refused by check_version as a version being worked on, which it is.
        candidate = named.removesuffix(marker_of(arguments.source))

        # The commit a release tags still names the version it released, and publishing a release creates that
        # tag, which a workflow running on push runs for as well. Asked there, `version` is not being asked to
        # release it again, so it says what the commit is and passes. A version handed in is still asked about.
        if not arguments.version and f"{prefix}{candidate}" in git("tag", "--points-at", "HEAD").split():
            print(f"note: this commit is the release of {candidate}, tagged {prefix}{candidate}", file=sys.stderr)
            print(candidate)
            return []
    else:
        # Handed in, or the default a dispatch leaves empty. No file is read, and nothing will be written.
        candidate = arguments.version or next_candidate(prefix)

    problems = check_version(candidate, released_versions(prefix))
    if not problems:
        print(candidate)
    return problems


def changelog_command(arguments) -> list[str]:
    in_tree = read_file("CHANGELOG.md", "the released sections")
    prefix = prefix_from(arguments.source, arguments.tag_prefix)

    at_tag = {}
    for version in released_versions(prefix):
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
    released = arguments.released.removeprefix(prefix_from(arguments.source, arguments.tag_prefix))
    if not SEMVER.match(released):
        return [f"'{arguments.released}' is not a version this project releases"]
    print(version_after(released) + marker_of(arguments.source))
    return []


# The exit status of `set-version` under a source that declares no version, apart from the 1 every other refusal of
# it gives and the 2 argparse gives a command line it cannot parse. A caller carrying on without writing has to tell
# "there is nothing to write to" from "the write failed", and only the first is safe to carry on from.
NOTHING_TO_WRITE = 3


def set_version_command(arguments) -> list[str]:
    """Write a version into the file the source declares one in, which a release does twice: the version it
    releases, before it builds, and the next one being worked on, once it is out."""
    if not declares_a_version(arguments.source):
        print(f"{arguments.source} declares no version, so there is nothing here to write one to",
              file=sys.stderr)
        raise SystemExit(NOTHING_TO_WRITE)

    adapter = SOURCES[arguments.source]
    path = repository() / adapter.file
    written = adapter.with_version(read_declared(adapter), arguments.version)
    with open(path, "w", encoding=adapter.encoding) as stream:
        stream.write(written)

    # Read back through the same reader everything else here uses. What this catches is a writer and a reader
    # that have come to disagree - the quiet failure, and the whole reason this is not a pattern in a shell script.
    if declared_version(arguments.source) != arguments.version:
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
    text = read_file("CHANGELOG.md", "the released sections")
    # Closed before the file is opened: opening it for writing empties it, and a refusal raised in between would
    # leave no changelog at all where the one it had should stand.
    written = closed(text, arguments.version, on, arguments.repository_url, prefix)
    with open(path, "w", encoding="utf-8") as stream:
        stream.write(written)
    print(f"[{arguments.version}] - {on}")
    return []


def notes_command(arguments) -> list[str]:
    """The text of one released section, below its heading: what the release notes say. Taken from the same
    file the changelog check holds to the tag, so the release page and the changelog cannot come to say
    different things, but for the warning release-flow/warn puts above the notes while publishing the release
    elsewhere has not completed - and refused where there is nothing to say, a release whose notes are empty being one
    nobody meant to make."""
    text = bodies(read_file("CHANGELOG.md", "the released sections")).get(arguments.version, "")
    if not text.strip():
        return [f"CHANGELOG.md holds nothing for {arguments.version}, so there are no notes to release it with"]
    print(text)
    return []


def channel_command(arguments) -> list[str]:
    version = arguments.version.removeprefix(prefix_from(arguments.source, arguments.tag_prefix))
    if not SEMVER.match(version):
        return [f"'{arguments.version}' is not a version this project releases"]
    print(channel_of(version))
    return []


def prefix_command(arguments) -> list[str]:
    """What release tags are called here. Printed rather than written into the workflows, so that a spelling
    the source declares is declared once and a repository cannot come to disagree with its own tags; a source
    declaring none is handed it, and this says it back."""
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
    prefix = prefix_from(arguments.source, arguments.tag_prefix)
    releases = released_versions(prefix)
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
    parser.add_argument("--source", required=True, choices=SOURCES,
                        help="where the version a release is asked to be comes from")
    parser.add_argument("--tag-prefix", help="what release tags carry in front of the version, for a source "
                                             "that declares no prefix of its own")
    commands = parser.add_subparsers(required=True)

    version_parser = commands.add_parser("version", help="whether the candidate version may be released next")
    version_parser.add_argument("--version", help="the version to release, not this program's: the one to "
                                                  "check instead of what the source declares, or of the version "
                                                  "after the highest release where it declares none, with or "
                                                  "without the marker that source puts on a declaration")
    version_parser.set_defaults(run=version_command)

    next_parser = commands.add_parser("next", help="the version that follows a released one, with the source's marker")
    next_parser.add_argument("released", help="the version just released, with or without the tag prefix")
    next_parser.set_defaults(run=next_command)

    changelog_parser = commands.add_parser("changelog", help="whether released sections still read as released")
    changelog_parser.set_defaults(run=changelog_command)

    set_version_parser = commands.add_parser("set-version", help="write a version where the source declares one")
    set_version_parser.add_argument("version", help="the version to write")
    set_version_parser.set_defaults(run=set_version_command)

    close_changelog_parser = commands.add_parser("close-changelog", help="close [Unreleased] into a released section")
    close_changelog_parser.add_argument("version", help="the version being released")
    close_changelog_parser.add_argument("--date", help="the date to give the section, today by default")
    close_changelog_parser.add_argument("--repository-url", help="write the versions' link definitions afresh, "
                                                                 "pointing into this repository; left alone "
                                                                 "without it")
    close_changelog_parser.set_defaults(run=close_changelog_command)

    notes_parser = commands.add_parser("notes", help="the text below one released section's heading, as "
                                                     "release notes")
    notes_parser.add_argument("version", help="the version whose notes to print")
    notes_parser.set_defaults(run=notes_command)

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
