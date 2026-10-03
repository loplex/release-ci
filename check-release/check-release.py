#!/usr/bin/env python3
"""Checks a repository before and after a release.

- `version`: whether the candidate version may be released next,
  given the releases already tagged and what waits under `[Unreleased]`.
- `next`: the version that follows a released one, with the source's marker.
- `changelog`: whether every released section still reads as it did when it was released.
- `ancestry`: whether every release tag is still reachable. A history rewrite can take one off.
- `prefix`: what release tags carry in front of the version.
  Read from the source where it declares one, so that the workflows do not have to repeat it.
- `channel`: the distribution channel of a version, read off its pre-release suffix.
- `set-version`: write a version where the project declares it: the released one, then the next.
- `close-changelog`: move what is under `[Unreleased]` into a section of its own.
  This and `set-version` are what a release writes.
- `notes`: the text below one released section's heading, which is what its release notes say.

The rules are plain functions over text, tags and booleans, so the tests beside this file can exercise them
without a repository to release.
"""

import argparse
import datetime
import re
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

import sources


def repository_root() -> Path:
    """The root of the repository being checked, asked of git in the working directory.

    This file runs from a checkout of its own repository, against the repository in the working directory,
    which is usually another one.
    A root taken from this file's path would then name the wrong repository, and nothing would fail:
    this repository has a CHANGELOG.md of its own for the checks to read instead.
    """
    rev_parse = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if rev_parse.returncode != 0:
        raise SystemExit("check-release.py has to be run inside the repository it is checking")
    return Path(rev_parse.stdout.strip())


# Resolved on first use, not when this file is loaded:
# - `--help` then works outside a repository;
# - a test can set a repository of its own here before anything reads it.
# A subcommand that reads the repository still refuses to run outside one, once the arguments are parsed.
REPO: Path | None = None


def repository() -> Path:
    global REPO
    if REPO is None:
        REPO = repository_root()
    return REPO


# A version is a semantic version, build metadata included, in SemVer 2.0.0's own grammar:
# no leading zeros, and a pre-release identifier is a number or holds a letter or a hyphen.
# That grammar is what lets precedence() order versions as the spec does.
# A shape the spec leaves undefined, such as `1.0.0-a..b` or `01.0.0`, does not match, so nothing has to order it.
# `re.ASCII` keeps `\d` to ASCII digits, as the spec has them: otherwise `1٠.0.0` would be ordered as 10.0.0.
# `\Z` ends the match where the text ends; `$` would let a trailing newline through.
#
# Build metadata, the `+` part, is accepted together with the spec's rule for it:
# "Build metadata MUST be ignored when determining version precedence."
# So neither of `1.0.0+a` and `1.0.0+b` comes after the other, and check_version says so in those words.
# Metadata is captured apart from the pre-release suffix, so it is not part of the channel either.
#
# The pre-release suffix names the distribution channel (see channel_of):
# `0.2.0-beta.1` is offered only to whoever subscribed to `beta`, and is a pre-release wherever it is published.
PRE_RELEASE_IDENTIFIER = r"(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)"
BUILD_METADATA = r"(?:[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)"
SEMVER = re.compile(
    rf"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    rf"(?:-({PRE_RELEASE_IDENTIFIER}(?:\.{PRE_RELEASE_IDENTIFIER})*))?(?:\+({BUILD_METADATA}))?\Z",
    re.ASCII,
)

# Headings are read the way CommonMark 0.31.2 section 4.2 reads an ATX heading:
# up to three spaces before the #s, spaces or tabs after them, and a closing run of #s after a space is not text.
# A narrower reading would silently count a section's or a group's entries under the heading before it.
SECTION_HEADING = re.compile(r"^ {0,3}##[ \t]+\[([^\]]+)\]", re.MULTILINE)
UNRELEASED_HEADING = re.compile(r"^ {0,3}##[ \t]+\[Unreleased\][^\n]*\n", re.MULTILINE)
GROUP_HEADING = re.compile(r"^ {0,3}###[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$", re.MULTILINE)

# The kinds of change Keep a Changelog names, in its order.
# A section merged from several is written in this order.
# A group of any other name follows these, in the order first met, and is kept: its text was released too.
KINDS = ("Added", "Changed", "Deprecated", "Removed", "Fixed", "Security")

# How far past the last final release each kind moves the version, by SemVer's rules 6 to 8:
# - patch: backward compatible bug fixes and nothing else (rule 6), so a change to existing functionality asks for more;
# - minor: functionality added or deprecated (rule 7), and a change too;
# - major: something a caller relied on and no longer has.
#   Among Keep a Changelog's kinds that is a removal; under any group, an entry marked **BREAKING**.
# A group of any other name, such as `### Documentation` or `### Dependencies`, asks for a patch.
# Every release is at least a patch anyway, and the groups people add are not new functionality.
# An empty `[Unreleased]` asks for a patch here too: close-changelog is what refuses to release it.
# The indices are the order in which successors() lists the three steps.
PATCH, MINOR, MAJOR = 0, 1, 2
STEP_NAMES = ("patch", "minor", "major")
STEP_OF_KIND = {"Added": MINOR, "Changed": MINOR, "Deprecated": MINOR, "Removed": MAJOR, "Fixed": PATCH,
                "Security": PATCH}
# An entry is a list item.
# A line of three or more dashes, stars or underscores alone is a thematic break, which CommonMark reads first.
LIST_ITEM = re.compile(r"^(?![ \t]*([-*_])(?:[ \t]*\1){2,}[ \t]*$)[ \t]*(?:[-*+]|\d{1,9}[.)])[ \t]+\S.*$", re.MULTILINE)
BREAKING_ENTRY = re.compile(r"^[ \t]*(?:[-*+]|\d{1,9}[.)])[ \t]+\*\*BREAKING:?\*\*", re.MULTILINE | re.IGNORECASE)
HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)

LINK_DEFINITION = re.compile(r"^\[[^\]]+\]:\s.*$", re.MULTILINE)


def precedence(version: str) -> tuple:
    """A key that orders versions the way SemVer does, so that `<` and `sorted` mean what the spec means.

    Two rules that string comparison gets wrong:
    - a release outranks every pre-release of the same three numbers: `0.2.0` > `0.2.0-rc.1`;
    - a numeric identifier in the suffix compares as a number: `beta.9` < `beta.10`.

    Build metadata is dropped, not ranked last, because the spec says so:
    two versions that differ only in metadata have the same precedence.
    Every caller has to cope with that equality; check_version is where it is met and named.
    """
    major, minor, patch, suffix, _ = SEMVER.match(version).groups()
    if suffix is None:
        return (int(major), int(minor), int(patch), 1, ())

    identifier_keys = tuple(
        (0, int(identifier), "") if identifier.isdigit() else (1, 0, identifier) for identifier in suffix.split(".")
    )
    return (int(major), int(minor), int(patch), 0, identifier_keys)


def being_worked_on(version: str) -> bool:
    """Whether SNAPSHOT is one of the dot- or hyphen-separated parts of the pre-release suffix of `version`.

    That covers `1.0.0-SNAPSHOT`, `1.0.0-rc.1-SNAPSHOT` and `1.0.0-SNAPSHOT-SNAPSHOT`.
    The last is what a script makes by appending the marker to a version that has it already.
    version_command strips one marker only, so its candidate still carries the other.
    `preSNAPSHOT` is not the marker.
    Build metadata is not looked at: it names a build, not a state."""
    suffix = SEMVER.match(version).group(4) or ""
    return "SNAPSHOT" in re.split(r"[.-]", suffix)


def core(version: str) -> tuple[int, int, int]:
    major, minor, patch, _, _ = SEMVER.match(version).groups()
    return (int(major), int(minor), int(patch))


def successors(released_core: tuple[int, int, int]) -> list[tuple[int, int, int]]:
    """The three cores SemVer allows after `released_core`: one part goes up by one, every part right of it to zero."""
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

    # The base rule: a release has to outrank the last release offered to the same people.
    # An update check, in an IDE or a package manager, offers a release by comparing versions,
    # so a release that does not outrank the last one is offered to nobody.
    # - A final release goes to everyone, so it has to outrank the last final release.
    #   Pre-releases reach only their channel's subscribers, so they do not count here:
    #   a hotfix 0.2.1 may go out while 0.3.0-beta.1 is open, and no channel is offered a downgrade.
    #   That holds only from a branch the train has not reached.
    #   Where the train's sections stand, check_step refuses the hotfix, since it would carry the train's changes.
    # - A pre-release goes to subscribers, who see every release, so it has to outrank the highest tag of all.
    #   So while a train is open, a hotfix cannot be tried on a channel first:
    #   0.2.1-rc.1 sorts below 0.3.0-beta.1 and is refused, while 0.2.1 itself passes.
    to_outrank = finals[-1] if is_final and finals else ordered[-1]
    if precedence(candidate) == precedence(to_outrank) and candidate != to_outrank:
        # Equal precedence with different text can only be build metadata, which SemVer leaves out of ordering.
        # It gets a message of its own: "does not come after" would read as wrong about a version that plainly
        # came later in time. What it does not do is outrank the release.
        problems.append(
            f"{candidate} and {to_outrank} differ only in build metadata, which SemVer leaves out of ordering: "
            f"neither comes after the other, so whoever compares versions is offered no release at all"
        )
        # No step is measured either: the candidate has that release's core,
        # and "does not follow" would be the misleading arithmetic this message replaces.
        return problems
    elif precedence(candidate) <= precedence(to_outrank):
        problems.append(f"{candidate} does not come after {to_outrank}, which is released already")

    # The step is measured from the last *final* release, not from the highest tag.
    # A pre-release train such as 0.2.0-rc.1, 0.2.0-rc.2, 0.2.0 then stays inside one allowed core.
    # Going backwards inside the train is what the check above refuses.
    # An open train also cannot be left for a core the last final release does not allow:
    # after 0.2.0, 0.4.0 is refused whatever 0.3.0-beta.1 says, and 1.0.0 is not.
    # With nothing final released yet, the open train is the only way on:
    # after 0.2.0-rc.1, a later pre-release of 0.2.0, or 0.2.0 itself.
    # Without this, a project that has only ever tagged pre-releases could name any core.
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
    """The version that follows `released`, without a marker. It is used two ways:
    - a project that declares its version writes it back as the next one being worked on;
      the source adds the marker, where it has one;
    - a repository versioned by its tags alone offers it as the default when a release is asked for.

    A pre-release moves nothing: `0.2.0-rc.1` was a step towards `0.2.0`, so work goes on towards it.
    A final release is followed by the smallest step, a patch.
    By the time of the release, `[Unreleased]` may ask for more, and check_step holds the release to it:
    - where the source declares a version, whoever lands a feature raises the version to a minor in the same
      pull request, where a reviewer sees the line.
      For a feature that landed while a release was out, that is the pull request carrying the release back,
      and its body says so.
    - where the source declares none, next_candidate moves the default as far as `[Unreleased]` asks.
    """
    major, minor, patch, suffix, _ = SEMVER.match(released).groups()  # Metadata names a build, not what follows it.
    if suffix is not None:
        return f"{major}.{minor}.{patch}"
    return f"{major}.{minor}.{int(patch) + 1}"


class Asked(NamedTuple):
    """What the entries under `[Unreleased]` ask of the version released with them."""
    step: int  # PATCH, MINOR or MAJOR
    why: str  # What asks for the step, the way a refusal names it; empty for a patch, which nothing refuses.
    unknown: list[str]  # Groups named outside Keep a Changelog's kinds, with no BREAKING entry: read as a patch.
    loose: list[str]  # Entries standing under no group at all.
    where: str = "[Unreleased]"  # The section `why` stands in.


NOTHING_ASKED = Asked(PATCH, "", [], [])


def asked_by(unreleased: str) -> Asked:
    """What the text under `[Unreleased]` asks of the next release: the largest step any group asks for,
    and what asks for it.

    - HTML comments count as nothing.
    - An empty group asks for nothing: an empty `### Removed` left as a reminder removes nothing.
    - An entry above the first group is under no kind, so nothing says how far it moves the version.
      It is handed back in `loose` for the caller to refuse, not counted as a patch.
    - Other text above the first group, such as a sentence introducing the section, is ignored.
    """
    unreleased = HTML_COMMENT.sub("", unreleased)
    marks = list(GROUP_HEADING.finditer(unreleased))
    lead = unreleased[: marks[0].start()] if marks else unreleased
    loose = [item.group(0).strip() for item in LIST_ITEM.finditer(lead)]
    step, why, unknown = PATCH, "", []
    for index, mark in enumerate(marks):
        name = mark.group(1)
        end = marks[index + 1].start() if index + 1 < len(marks) else len(unreleased)
        text = unreleased[mark.end() : end]
        if not text.strip():
            continue
        if BREAKING_ENTRY.search(text):
            asks, reason = MAJOR, f"an entry marked **BREAKING** under ### {name}"
        else:
            asks, reason = STEP_OF_KIND.get(name, PATCH), f"### {name}"
            if name not in STEP_OF_KIND:
                unknown.append(name)
        if asks > step:
            step, why = asks, reason
    return Asked(step, why, unknown, loose)


def least_step(asked: int, released: str) -> int:
    """The step `asked` comes to after the final release `released`.

    Below 1.0, a breaking change moves the minor, as Cargo and npm read `^0.y`.
    SemVer's rule 4 promises nothing for 0.y.z,
    and 1.0 is a step taken on purpose, not because something was removed."""
    return MINOR if asked == MAJOR and core(released)[0] == 0 else asked


def check_step(candidate: str, releases: list[str], asked: Asked) -> list[str]:
    """Whether `candidate` moves far enough past the last final release for what `asked` says it releases.

    Measured from the last final release, as the step in check_version is,
    so a pre-release of the version it heads for passes wherever that version would.
    With nothing final released there is no step.
    A candidate outside the allowed steps is check_version's to refuse, not this function's.

    `asked` comes from train_asks: `[Unreleased]`, and the pre-release sections above the last final release.
    A release cut where those sections stand carries their changes as well.
    """
    finals = sorted((version for version in releases if SEMVER.match(version) and SEMVER.match(version).group(4)
                     is None), key=precedence)
    if not finals:
        return []
    permitted = successors(core(finals[-1]))
    least = least_step(asked.step, finals[-1])
    if core(candidate) not in permitted or permitted.index(core(candidate)) >= least:
        return []
    return [f"{asked.where} holds {asked.why}, so the release after {finals[-1]} is at least a "
            f"{STEP_NAMES[least]}, {core_text(permitted[least])}, and {candidate} is not"]


def train_asks(found: dict[str, str], releases: list[str]) -> Asked:
    """What a changelog asks of the next release: the most that `[Unreleased]`, or any pre-release section above
    the last final release, asks for. `found` is the changelog by section, as bodies() gives it.

    A release is cut from a branch, and the changelog on that branch says what it carries.
    Where it holds the sections of an open train, such as 0.3.0-beta.1 with `### Added`,
    the branch carries the train's changes, and a hotfix 0.2.1 cut from it would release them as a patch.
    A branch the train never reached has no such section, and is held to its `[Unreleased]` alone.
    Closing the train, or going on with it, moves the core that far anyway.
    Loose entries and unknown group names are handed back for `[Unreleased]` only:
    a released section is not this release's to refuse.
    """
    asked = asked_by(found.get("Unreleased", ""))
    finals = sorted((version for version in releases if SEMVER.match(version) and SEMVER.match(version).group(4)
                     is None), key=precedence)
    if not finals:
        return asked
    for label, text in found.items():
        if SEMVER.match(label) and SEMVER.match(label).group(4) is not None \
                and precedence(label) > precedence(finals[-1]):
            train = asked_by(text)
            if train.step > asked.step:
                asked = asked._replace(step=train.step, why=train.why, where=f"[{label}]")
    return asked


def channel_of(version: str) -> str:
    """The distribution channel a version is published to:
    the first identifier of its pre-release suffix, or `default` for a final release.

    - `0.3.0-beta.1` goes to `beta`, and is offered only to whoever subscribed to that channel.
    - `0.3.0` goes to everyone.
    - Identifiers are separated by dots, and a hyphen is an ordinary character inside one:
      `1.0.0-eap.2` names the channel `eap`, and `1.0.0-eap-2` names `eap-2`, a channel per build.
      That is a thing to spell on purpose, not to meet by accident.
    - Build metadata is not part of it: `0.3.0-beta.1+sha.5114f85` goes to `beta`, and `1.0.0+dfsg1` to everyone.

    Such a name is for channels on the JetBrains Marketplace and dist-tags on npm.
    A registry with nothing of the kind gets the same answer; what a pre-release suffix means there is for its
    publishing step to decide.

    Whatever marks a release as a pre-release, or uploads it to a channel, should ask this rather than repeat the
    rule. A project whose own publishing task needs the channel has to repeat the rule there, and keep both alike.
    """
    suffix = SEMVER.match(version).group(4)
    if suffix is None:
        return "default"
    return suffix.split(".")[0]


def sections(changelog: str) -> dict[str, str]:
    """Each section of a changelog, by the label in its heading: a version, or `Unreleased`.

    Link definitions are left out wherever they stand, so one inside a section is not compared either.
    The ones at the foot of the file belong to no section, and a release may write them afresh."""

    text = LINK_DEFINITION.sub("", changelog)
    found = {}
    marks = list(SECTION_HEADING.finditer(text))
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(text)
        found[mark.group(1)] = text[mark.end() : end].strip()
    return found


def check_changelog(in_tree: str, at_tag: dict[str, str], off_history: set[str] | None = None) -> list[str]:
    """Whether every released section still reads as it did at the tag that released it.

    `at_tag` maps a version to CHANGELOG.md as it stood at that version's tag.
    A released section has been published: as the release notes on GitHub, and as the registry's notes.
    Changing it afterwards makes the repository disagree with what readers were given.

    `off_history` holds the versions whose tag this history does not reach (what `ancestry` checks).
    A missing section is told apart by it:
    - Between publishing a release and its branch reaching the default branch, the section exists only where
      the tag is. "Gone" would accuse somebody of deleting it, so the message says the release has yet to arrive.
    - Otherwise the section was removed.
    Both fail.
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
    """The released versions whose tag predates their section, so check_changelog has nothing to compare them to.

    The report names them instead of counting them as compared.
    Otherwise a run that compared nothing would read the same as one that compared everything."""
    return sorted((version for version, text in at_tag.items() if version not in sections(text)), key=precedence)


def bodies(changelog: str) -> dict[str, str]:
    """Each section's text below its heading line, by the label in its heading.

    Unlike sections(), this leaves out the rest of the heading line, the date, which would read as a first entry.
    Link definitions are left out, as there."""
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
    """Several sections' text merged into one.

    - Text before a section's first `###` goes at the top.
    - Each group's entries go together under one heading of its name, in the order the texts come in.
    - Groups are ordered as KINDS has them, other names after."""
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


def compared_from(version: str, below: list[str]) -> str | None:
    """The release a section's link compares from, which is the one its entries are counted from.

    It is the highest of the sections `below` it in the file that SemVer puts before it.
    For a final release, only final releases count.
    None where there is none: the link then points at the version's own commits.
    - A final release passes over the pre-releases. Its section took in the entries of every one since the final release
      before it (see closed()), so a link from the last of them would leave out the train the section took in.
    - A pre-release counts both kinds. beta.2 after a hotfix 0.2.1 compares from beta.1.
      0.3.0-beta.1 after a 0.2.0 that closed its own train compares from 0.2.0, not from 0.2.0-beta.2.
    - A backport released after a newer line is not what that line compares from: precedence decides, not
      the order in the file.
    - A section whose label is not SemVer compares from the section below it.

    The Gradle changelog plugin compares every section from the one below it.
    The two agree on a changelog of final releases in order.
    semantic-release picks the release before a final one the same way."""
    if SEMVER.match(version) is None:
        return below[0] if below else None
    final = SEMVER.match(version).group(4) is None
    earlier = [label for label in below if SEMVER.match(label) and precedence(label) < precedence(version)
               and not (final and SEMVER.match(label).group(4) is not None)]
    return max(earlier, key=precedence, default=None)


def linked(changelog: str, repository_url: str, prefix: str) -> str:
    """The changelog with its link definitions written afresh.

    - [Unreleased] compares from the newest release to HEAD.
    - Each release compares from the one compared_from gives it.

    They are rewritten whole, because every release changes the first of them.
    That is also why check_changelog leaves them out.
    Only these definitions are replaced: one the changelog keeps for a link of its own, such as to
    Keep a Changelog, stays where it is."""
    versions = [version for version in sections(changelog) if version != "Unreleased"]
    definitions = []
    if versions:
        definitions.append(f"[Unreleased]: {repository_url}/compare/{prefix}{versions[0]}...HEAD")
    for index, version in enumerate(versions):
        start = compared_from(version, versions[index + 1 :])
        target = f"compare/{prefix}{start}...{prefix}{version}" if start else f"commits/{prefix}{version}"
        definitions.append(f"[{version}]: {repository_url}/{target}")
    labels = {"Unreleased", *versions}
    kept = [line for line in changelog.split("\n")
            if not (LINK_DEFINITION.fullmatch(line) and line[1 : line.index("]")] in labels)]
    text = "\n".join(kept).rstrip("\n")
    return text + ("\n\n" + "\n".join(definitions) if definitions else "") + "\n"


def closed(changelog: str, version: str, on: str, repository_url: str | None = None, prefix: str = "") -> str:
    """The changelog with everything under `[Unreleased]` moved into a section of its own, dated `on`.

    A release does this to the file before it is published.
    It is the counterpart of check_changelog: the section written here may never be edited again,
    because the tag is about to hold a copy of it.

    Refused rather than written:
    - a file with no `[Unreleased]` section: there is nothing to close;
    - a version that already has a section: this has run twice, or a section was written by hand,
      and closing again would bury one of them;
    - an empty `[Unreleased]`: a release with nothing to say, and every later check would compare against that.

    Link definitions at the foot of the file belong to the file, not to the section, so they stay where they are.
    Changelogs with them and without them are both in use.
    Given the repository's URL, they are written afresh instead, as linked() writes them.

    A final release takes into its section the entries of every pre-release since the final release before it,
    in SemVer's order, whatever version they were for. That earlier final release is what compared_from gives.
    - Whoever skipped the betas reads everything 0.3.0 brings in one place.
    - 1.0.0 after an abandoned 0.3.0-beta.1 also says what that beta brought.
      semantic-release's notes for a final release likewise cover everything since the last final one.
    - A hotfix below an open train takes none of it, and a pre-release takes nothing in.
    - The pre-release sections stay as they were: released, and held to their tags.
    Emptiness is judged on the resulting section, so a train with nothing new to say at its end still closes.

    The Gradle changelog plugin's `combinePreReleases`, on by default, does the same only for pre-releases of
    the release's own version, and leaves an abandoned train out.
    Its code does not check that the release is a final one, so it would let 0.3.0-beta.2 take in 0.3.0-beta.1,
    repeating to a channel what it was already offered.
    Its documentation speaks of the final release, and so does this.
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
        found = bodies(changelog)
        start = compared_from(version, [label for label in found if label != "Unreleased"])
        train_entries = [
            text for label, text in found.items()
            if SEMVER.match(label) and SEMVER.match(label).group(4) is not None
            and precedence(label) < precedence(version) and (start is None or precedence(start) < precedence(label))
        ]
        if train_entries:
            entries = combined([entries, *train_entries])
    if not entries:
        if is_final:
            span = f"between {start} and {version}" if start else f"below {version}"
            reason = (f", and nothing in the pre-releases {span} to take in" if train_entries
                      else f", and no pre-release {span} to take in")
        elif SEMVER.match(version):
            reason = f", and {version}, a pre-release, takes no other one in"
        else:
            reason = ""
        raise SystemExit(f"nothing is under [Unreleased]{reason}, so there is nothing to release")

    # The blank line before whatever follows is written here, not inherited:
    # the blank lines between [Unreleased] and the section below were just taken off the end of the entries.
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

    A tag points at the commit a release was made from, and is the only record of which commit that was.
    Anything that rewrites the commits around it leaves the tag on a commit this history no longer reaches:
    a squash merge, a rebase merge, GitHub's `Update with rebase`, a force-push.

    Asking whether the tag is reachable catches all of them, whatever the cause.
    Forbidding the causes one by one would not: GitHub can add new ways to rewrite a branch.

    `held_by` names, for a tag that is not on this history, a branch that still holds it.
    A release whose branch has not been carried back yet fails the same way as one a rewrite orphaned.
    The message differs, because the cause and the fix differ:
    blaming a rewrite for a merge that is only outstanding sends the reader looking for damage that is not there.

    A branch holding the tag does not tell the two apart:
    a squash or rebase merge replays the release commit and leaves the original on the branch it came from.
    So that message names both readings; both are settled by looking at that one branch.
    Only a tag that no branch holds is put down to a rewrite outright.
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


def read_file(name: str, holds: str, encoding: str = "utf-8", newline: str | None = None) -> str:
    """A file of the repository, read as text.

    A missing file is refused with its name and what it is read for.
    A traceback would read as the tool breaking, not as the repository lacking a file, and would name no fix.

    `newline` is open()'s: left out, line endings are read as `\\n`.
    A writer that wants to keep the file's own line endings passes `""`."""
    try:
        with open(repository() / name, encoding=encoding, newline=newline) as stream:
            return stream.read()
    except FileNotFoundError:
        raise SystemExit(f"there is no {name} here, and it is where {holds} would be read from") from None


def read_declared(adapter, newline: str | None = None) -> str:
    """The file an adapter declares its version in, read in the adapter's encoding."""
    return read_file(adapter.file, adapter.holds, adapter.encoding, newline)


# Where the version of a release comes from is the one thing here that depends on the kind of project.
# sources.py decides it, with one adapter per kind of repository.
# The rules ask an adapter four things, through the functions below:
# whether it declares a version, its marker for a version being worked on, the version it names, the tag prefix.
# set_version_command also hands it the text to rewrite.
# The file an adapter names is read and written here, in the adapter's `encoding`.
# read_declared() reads it, with the adapter's `holds` saying what the file is read for,
# so a missing file is refused the same way whatever the format.
# The top of sources.py lists everything an adapter answers.
SOURCES = sources.SOURCES


def declares_a_version(source: str) -> bool:
    """Whether the source names the version between releases, so that a release reads it there.

    Where it does, a release writes the next version back afterwards.
    Where it does not, `set-version` has nothing to write to, and says so instead of reporting a success."""
    return SOURCES[source].declares_a_version


def marker_of(source: str) -> str:
    """The ending a version has while it is being worked on, hyphen included: `-SNAPSHOT` for gradle.properties.

    Empty where the source has no such state:
    a repository whose version lives only in its tags has no version being worked on."""
    return SOURCES[source].marker


def declared_version(source: str) -> str:
    """The version a declaring source names, marker included.
    Without the marker, it is what a release is asked to be."""
    adapter = SOURCES[source]
    return adapter.version(read_declared(adapter))


def as_text(value: str, named_in: str) -> str:
    """`value` as given, or a refusal where it holds a lone UTF-16 surrogate.

    A lone surrogate is what a command-line byte that does not decode arrives as (PEP 383).
    It is also what gradle.properties reads an unpaired `\\uD800`-`\\uDFFF` escape as, as Java does.
    Neither UTF-8 nor UTF-16 can encode one, so printing or writing it ends in a traceback,
    and a file already opened for writing would be left empty."""
    if any("\ud800" <= character <= "\udfff" for character in value):
        raise SystemExit(f"{named_in} is {ascii(value)}, which holds a lone UTF-16 surrogate - a command-line byte "
                         "that does not decode, or an unpaired \\uD800-\\uDFFF escape - and is no text")
    return value


def prefix_from(source: str, given: str | None) -> str:
    """What a release tag carries in front of its version: `v` in `v0.1.0`, nothing in `0.1.0`.

    Both spellings are in use, so the prefix is declared, never assumed, and there is no default here.
    A wrong guess would pass: a repository that tags bare versions, read as tagging `v*`, has no release tags,
    and every check then passes without comparing anything, with only a note on stderr.
    The exception is `version` under `tags` with no version given: it fails, finding no release to count from.
    A caller that wants a default declares it where its own readers can see it.

    A declared prefix that is not text (see as_text) is refused here, as main() refuses one on the command line.
    No tag name can be spelled with it, so `prefix` would end in a traceback printing it,
    and every other check would pass having found no release.
    """
    if given is not None:
        return given
    adapter = SOURCES[source]
    if adapter.file is not None:
        return as_text(adapter.tag_prefix(read_declared(adapter)), f"tagPrefix in {adapter.file}")
    raise SystemExit(f"--tag-prefix says what release tags are called, which {source} does not declare")


def next_candidate(releases: list[str], asked: Asked = NOTHING_ASKED) -> str:
    """The version to release when nobody says which.

    It is the version after the highest release, or, where that is further,
    the least step past the last final release that `asked` allows.
    A dispatch form cannot compute a default, so its field is left empty and this fills it in.
    With nothing released there is nothing to count from, so the first version has to be named.
    """
    if not releases:
        raise SystemExit("nothing is released here to count from, so say which version to release")
    after = version_after(sorted(releases, key=precedence)[-1])
    finals = sorted((version for version in releases if SEMVER.match(version).group(4) is None), key=precedence)
    if not finals or not check_step(after, releases, asked):
        return after
    return core_text(successors(core(finals[-1]))[least_step(asked.step, finals[-1])])


def unreleased_asks(releases: list[str]) -> Asked:
    """What CHANGELOG.md asks of the next release, by train_asks.
    Groups under `[Unreleased]` named outside Keep a Changelog's kinds are noted on stderr.

    A repository without the file is asked for a patch at most, with a note on stderr, not refused:
    `version` still compares what it can over the tags,
    and a check that only reads a changelog should not force a project to keep one.
    The same goes for a file with no `[Unreleased]` section, such as `## Unreleased` without the brackets.
    """
    if not (repository() / "CHANGELOG.md").exists():
        print("note: there is no CHANGELOG.md here, so nothing under [Unreleased] says how far the version has to "
              "move", file=sys.stderr)
        return NOTHING_ASKED
    found = bodies(read_file("CHANGELOG.md", "what waits to be released"))
    if "Unreleased" not in found:
        print("note: CHANGELOG.md has no [Unreleased] section, so nothing under it says how far the version has "
              "to move", file=sys.stderr)
        return NOTHING_ASKED
    asked = train_asks(found, releases)
    for name in asked.unknown:
        print(f"note: [Unreleased] has a group '### {name}', which is not a kind of change Keep a Changelog names, "
              f"so it asks for no more than a patch", file=sys.stderr)
    return asked


def released_versions(prefix: str) -> list[str]:
    """Every tag that names a release, with the prefix taken off.

    A repository also has tags that are not releases, and those are left out:
    another component's, a deployment's, a milestone's, and a version tagged while it was still being worked on.

    Finding no release among the tags is reported on stderr, not failed:
    a repository may carry other tags only, and a first release has nothing to compare with either.
    But it is also what a wrong prefix looks like, and every check over the result then passes without comparing
    anything. Only `version` under `tags` with no version given fails instead, finding no release to count from.

    Tags are selected by how they start, not by a glob, so a prefix is read as text and not as a pattern,
    and the number of tags passed over comes with the selection.
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
    prefix = prefix_from(arguments.version_source, arguments.tag_prefix)

    if declares_a_version(arguments.version_source):
        named = arguments.version or declared_version(arguments.version_source)

        # Work carries the marker, and a release drops it:
        # the released version is the version worked on without the marker, so the two cannot drift apart.
        # Only a marker at the very end comes off, and a version handed in may be given with or without it.
        # One still carrying it after that, such as `1.0.0-SNAPSHOT+b`, is refused by check_version
        # as a version being worked on, which it is.
        candidate = named.removesuffix(marker_of(arguments.version_source))

        # The commit a release tags still names the version it released.
        # Publishing the release creates that tag, and a workflow that runs on push runs for it too.
        # There `version` is not being asked to release it again, so it says what the commit is and passes.
        # A version handed in is still checked.
        if not arguments.version and f"{prefix}{candidate}" in git("tag", "--points-at", "HEAD").split():
            print(f"note: this commit is the release of {candidate}, tagged {prefix}{candidate}", file=sys.stderr)
            print(candidate)
            return []
        releases = released_versions(prefix)
        asked = unreleased_asks(releases)
    else:
        # Handed in, or the default where a dispatch left it empty. No file is read, and none will be written.
        releases = released_versions(prefix)
        asked = unreleased_asks(releases)
        candidate = arguments.version or next_candidate(releases, asked)

    problems = check_version(candidate, releases) or check_step(candidate, releases, asked)
    problems += [f"[Unreleased] has an entry under no ### group, so nothing says what kind of change it is: {entry}"
                 for entry in asked.loose]
    if not problems:
        print(candidate)
    return problems


def changelog_command(arguments) -> list[str]:
    in_tree = read_file("CHANGELOG.md", "the released sections")
    prefix = prefix_from(arguments.version_source, arguments.tag_prefix)

    at_tag = {}
    for version in released_versions(prefix):
        try:
            at_tag[version] = git("show", f"{prefix}{version}:CHANGELOG.md")
        except subprocess.CalledProcessError:
            # Tagged before the file existed, so there is no section to compare.
            # It is reported below, with the tags older than their section.
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
    released = arguments.released.removeprefix(prefix_from(arguments.version_source, arguments.tag_prefix))
    if not SEMVER.match(released):
        return [f"'{arguments.released}' is not a version this project releases"]
    print(version_after(released) + marker_of(arguments.version_source))
    return []


# The exit status of `set-version` under a source that declares no version.
# Every other refusal of it exits with 1, and argparse exits with 2 on a command line it cannot parse.
# A caller has to tell "there is nothing to write to" from "the write failed": only the first is safe to go on from.
NOTHING_TO_WRITE = 3


def set_version_command(arguments) -> list[str]:
    """Write a version into the file the source declares it in. A release does this twice:
    the version it releases, before the build, and the next one to work on, once the release is out."""
    if not declares_a_version(arguments.version_source):
        print(f"{arguments.version_source} declares no version, so there is nothing here to write one to",
              file=sys.stderr)
        raise SystemExit(NOTHING_TO_WRITE)

    # Read and written with the file's own line endings, so a CRLF file is not rewritten whole to change one line.
    adapter = SOURCES[arguments.version_source]
    path = repository() / adapter.file
    written = adapter.with_version(read_declared(adapter, newline=""), arguments.version)
    with open(path, "w", encoding=adapter.encoding, newline="") as stream:
        stream.write(written)

    # Read back through the same reader everything else here uses.
    # That catches a writer and a reader that have come to disagree, which would otherwise fail silently.
    # It is the reason this is not a pattern in a shell script.
    if declared_version(arguments.version_source) != arguments.version:
        return [f"{arguments.version_source} still does not name {arguments.version} after being rewritten"]
    print(arguments.version)
    return []


def close_changelog_command(arguments) -> list[str]:
    """Close [Unreleased] into a section for the version being released.
    A release does this to the file before it is published."""
    path = repository() / "CHANGELOG.md"
    on = arguments.date or datetime.date.today().isoformat()
    # The prefix is needed only to write links.
    # A source that declares none should not need one just to close a section.
    prefix = prefix_from(arguments.version_source, arguments.tag_prefix) if arguments.repository_url else ""
    # Written back with one line ending: CRLF where the file has any, else a lone CR where it has one, LF otherwise.
    # So a CRLF file is not rewritten whole to add one section.
    # A file mixing them comes back all in the first of these it holds.
    # A lone CR ends a line too, as open() reads one by default.
    # closed() works on LF text either way.
    raw = read_file("CHANGELOG.md", "the released sections", newline="")
    ending = "\r\n" if "\r\n" in raw else "\r" if "\r" in raw else "\n"
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    # The new text is computed before the file is opened: opening it for writing empties it,
    # and a refusal raised in between would leave no changelog at all.
    written = closed(text, arguments.version, on, arguments.repository_url, prefix)
    with open(path, "w", encoding="utf-8", newline=ending) as stream:
        stream.write(written)
    print(f"[{arguments.version}] - {on}")
    return []


def notes_command(arguments) -> list[str]:
    """The text of one released section, below its heading: what the release notes say.

    It comes from the same file the changelog check holds to the tag, so the release page and the changelog
    cannot drift apart. The one difference is the warning release-flow/warn puts above the notes while
    publishing the release elsewhere has not completed.
    An empty section is refused: nobody means to make a release whose notes are empty."""
    text = bodies(read_file("CHANGELOG.md", "the released sections")).get(arguments.version, "")
    if not text.strip():
        return [f"CHANGELOG.md holds nothing for {arguments.version}, so there are no notes to release it with"]
    print(text)
    return []


def channel_command(arguments) -> list[str]:
    if not SEMVER.match(arguments.version):
        return [f"'{arguments.version}' is not a version; channel takes one without the tag prefix"]
    print(channel_of(arguments.version))
    return []


def prefix_command(arguments) -> list[str]:
    """What release tags carry in front of the version here.

    Printed for the workflows instead of written into them, so a prefix the source declares is declared once,
    and a repository cannot come to disagree with its own tags.
    A source that declares none is handed the prefix, and this prints it back."""
    print(prefix_from(arguments.version_source, arguments.tag_prefix))
    return []


def unreachable(prefix: str, versions) -> set[str]:
    """The released versions whose tag this history does not reach.

    Asked of git in one place and handed to each check that needs it,
    so two checks of one repository cannot disagree about which releases are on it."""
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

    Asked only for a tag that HEAD does not reach, to choose between the two messages of check_ancestry.
    - Remote branches are asked first, and named as fetched: a release is carried back from what the remote has,
      and a local branch of the same name may hold something else.
    - Among the branches of the first kind that holds the tag, `release/<version>` comes first,
      because it is the one the reader has to act on.
    """
    wanted = f"release/{version}"
    for pattern in ("refs/remotes", "refs/heads"):
        branches = git("for-each-ref", "--contains", tag, "--format=%(refname:short)", pattern).split()
        if branches:
            return sorted(branches, key=lambda name: (name != wanted and not name.endswith("/" + wanted), name))[0]
    return ""


def ancestry_command(arguments) -> list[str]:
    prefix = prefix_from(arguments.version_source, arguments.tag_prefix)
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
    commands = parser.add_subparsers(required=True)

    # A command refuses the options it never reads.
    # `notes` and `channel` read neither, and `set-version` writes a version but names no tag.
    # `close-changelog` reads both only with --repository-url, and takes them either way.
    version_source = argparse.ArgumentParser(add_help=False)
    version_source.add_argument("--version-source", required=True, choices=SOURCES,
                                help="where the version of the next release comes from")
    tag_prefix = argparse.ArgumentParser(add_help=False)
    tag_prefix.add_argument("--tag-prefix", help="what release tags carry in front of the version, for a source "
                                                 "that declares no prefix of its own")
    both = [version_source, tag_prefix]

    version_parser = commands.add_parser("version", parents=both,
                                         help="whether the candidate version may be released next")
    version_parser.add_argument("--version", help="the version to release, not this program's: the one to "
                                                  "check instead of what the source declares, or of the version "
                                                  "after the highest release, or a later one [Unreleased] asks "
                                                  "for, where it declares none, with or without the marker that "
                                                  "source puts on a declaration")
    version_parser.set_defaults(run=version_command)

    next_parser = commands.add_parser("next", parents=both,
                                      help="the version that follows a released one, with the source's marker")
    next_parser.add_argument("released", help="the version just released, with or without the tag prefix")
    next_parser.set_defaults(run=next_command)

    changelog_parser = commands.add_parser("changelog", parents=both,
                                           help="whether released sections still read as released")
    changelog_parser.set_defaults(run=changelog_command)

    set_version_parser = commands.add_parser("set-version", parents=[version_source],
                                             help="write a version where the source declares one")
    set_version_parser.add_argument("version", help="the version to write")
    set_version_parser.set_defaults(run=set_version_command)

    close_changelog_parser = commands.add_parser("close-changelog", parents=both,
                                                 help="close [Unreleased] into a released section")
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

    prefix_parser = commands.add_parser("prefix", parents=both, help="what release tags carry in front of the version")
    prefix_parser.set_defaults(run=prefix_command)

    channel_parser = commands.add_parser("channel", help="the distribution channel a version is published to")
    channel_parser.add_argument("version", help="the version, without the tag prefix")
    channel_parser.set_defaults(run=channel_command)

    ancestry_parser = commands.add_parser("ancestry", parents=both,
                                          help="whether every released tag is still reachable")
    ancestry_parser.set_defaults(run=ancestry_command)

    arguments = parser.parse_args()
    # Arguments that are not text are refused once, here, not wherever an argument is printed or written.
    # Every subcommand, including any added later, is then handed text.
    for name, value in vars(arguments).items():
        if isinstance(value, str):
            as_text(value, f"the {name.replace('_', '-')} argument")
    problems = arguments.run(arguments)

    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
