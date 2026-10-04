"""CHANGELOG.md in the Keep a Changelog format: its sections, closing `[Unreleased]`, and its links.

Plain functions over the file's text, with no repository behind them.
"""

import re

from .versions import SEMVER, precedence


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

LINK_DEFINITION = re.compile(r"^\[[^\]]+\]:\s.*$", re.MULTILINE)


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
