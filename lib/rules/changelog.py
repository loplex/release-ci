"""CHANGELOG.md in the Keep a Changelog format: its sections, closing `[Unreleased]`, and its links.

Plain functions over the file's text, with no repository behind them.
"""

import re

from .markdown import Line, Unread, read, reading
from .versions import SEMVER, precedence


# A section's heading is a `##` heading whose text starts with its label in brackets: `## [1.0.0] - 2026-10-05`.
LABEL = re.compile(r"\[([^\]]+)\]")

# The kinds of change Keep a Changelog names, in its order.
# A section merged from several is written in this order.
# A group of any other name follows these, in the order first met, and is kept: its text was released too.
KINDS = ("Added", "Changed", "Deprecated", "Removed", "Fixed", "Security")


def says_something(text: str) -> bool:
    """Whether `text` holds a character str.isprintable() accepts, the space aside: what a release has to say.

    isprintable() rejects the characters of Unicode's Other and Separator categories but the space, so white space,
    a no-break space, a zero-width space, a soft hyphen, a control character, a private use character and one not
    assigned yet say nothing.
    Which are assigned is up to the Unicode version of the Python this runs on.
    Any other character says something, even one drawn blank, such as U+3164."""
    return any(char.isprintable() and char != " " for char in text)


def structure(changelog: str) -> list[Line]:
    """What each line of a changelog is (see markdown.read), or a refusal naming the first line not read here."""
    try:
        return read(changelog)
    except Unread as unread:
        raise SystemExit(f"CHANGELOG.md {unread}") from None


class UnreadCopy(SystemExit):
    """through()'s refusal of a copy at a tag, telling whether the section of the label began above the line refused.
    Where it did, the tag holds that section; where it did not, nothing says whether the tag holds one at all."""

    def __init__(self, message: str, began: bool):
        super().__init__(message)
        self.began = began


def through(changelog: str, label: str) -> str:
    """The changelog down to the end of the section of `label`, read no further, or a refusal naming a line above it.

    It reads the copy at a release tag, which cannot be edited, so the refusal does not say what to write instead.

    Where a section starts depends on every line above it: a fenced code block opened there can hide its heading.
    Nothing below it does, so a line there not read here does not matter to it.
    Without that section, the whole changelog is read."""
    lines, inside = changelog.split("\n"), False
    try:
        for index, line in enumerate(reading(changelog)):
            heading = LABEL.match(line.text) if line.kind == "heading" and line.level == 2 else None
            if heading and inside:
                return "\n".join(lines[:index])
            inside = inside or bool(heading and heading.group(1) == label)
    except Unread as unread:
        raise UnreadCopy(f"CHANGELOG.md {unread.found}", inside) from None
    return changelog


def marks(changelog: str) -> list[tuple[int, str]]:
    """The sections' headings, as the index of each heading's line and the label in it."""
    found = []
    for index, line in enumerate(structure(changelog)):
        label = LABEL.match(line.text) if line.kind == "heading" and line.level == 2 else None
        if label:
            found.append((index, label.group(1)))
    return found


def groups(text: str) -> list[tuple[int, str]]:
    """The `###` headings of a section's text, as the index of each heading's line and its name."""
    return [(index, line.text) for index, line in enumerate(structure(text)) if line.kind == "heading"
            and line.level == 3]


def undefined(changelog: str) -> list[str]:
    """The changelog's lines, with each link definition's line left empty."""
    lines = changelog.split("\n")
    return ["" if line.kind == "definition" else lines[index] for index, line in enumerate(structure(changelog))]


def sections(changelog: str) -> dict[str, str]:
    """Each section of a changelog, by the label in its heading: a version, or `Unreleased`.

    Link definitions are left out wherever they stand, so one inside a section is not compared either.
    The ones at the foot of the file belong to no section, and a release may write them afresh."""

    lines, found = undefined(changelog), {}
    headings = marks(changelog)
    for at, (index, label) in enumerate(headings):
        end = headings[at + 1][0] if at + 1 < len(headings) else len(lines)
        heading = lines[index]
        rest = heading[heading.index("]", heading.index("[")) + 1 :]  # The date, after the label.
        # Only spaces and tabs are taken off, with the line ends: a no-break space is text to CommonMark.
        found[label] = "\n".join([rest, *lines[index + 1 : end]]).strip(" \t\r\n")
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
            problems.append(missing(version, off_history))
        elif current[version] != was:
            problems.append(f"[{version}] is released but its section no longer reads as the tag has it")

    return problems


def missing(version: str, off_history: set[str]) -> str:
    """The problem with a released section the tree does not have, told apart as check_changelog says."""
    if version in off_history:
        return (f"[{version}] is released but its section is not on this history, and neither is the tag that "
                f"released it: the release has yet to reach here")
    return f"[{version}] is released but its section is gone"


def uncompared(at_tag: dict[str, str]) -> list[str]:
    """The released versions whose tag predates their section, so check_changelog has nothing to compare them to.

    The report names them instead of counting them as compared.
    Otherwise a run that compared nothing would read the same as one that compared everything."""
    return sorted((version for version, text in at_tag.items() if version not in sections(text)), key=precedence)


def bodies(changelog: str) -> dict[str, str]:
    """Each section's text below its heading line, by the label in its heading.

    Unlike sections(), this leaves out the rest of the heading line, the date, which would read as a first entry.
    Link definitions are left out, as there."""
    lines, found = undefined(changelog), {}
    headings = marks(changelog)
    for at, (index, label) in enumerate(headings):
        end = headings[at + 1][0] if at + 1 < len(headings) else len(lines)
        found[label] = "\n".join(lines[index + 1 : end]).strip("\n")
    return found


def joined(entries: list[str]) -> str:
    """One group's entries from several sections, one after another.
    Where one section's entries end with a link definition, a blank line follows it: CommonMark reads some lines right
    after a definition as part of it, so read() refuses any line there."""
    text = entries[0]
    for more in entries[1:]:
        text += ("\n\n" if structure(text)[-1].kind == "definition" else "\n") + more
    return text


def combined(texts: list[str]) -> str:
    """Several sections' text merged into one.

    - Text before a section's first `###` goes at the top.
    - Each group's entries go together under one heading of its name, in the order the texts come in (see joined()).
    - Groups are ordered as KINDS has them, other names after."""
    leads, merged = [], {}
    for text in texts:
        lines, headings = text.split("\n"), groups(text)
        lead = "\n".join(lines[: headings[0][0]] if headings else lines).strip("\n")
        if lead:
            leads.append(lead)
        for at, (index, name) in enumerate(headings):
            end = headings[at + 1][0] if at + 1 < len(headings) else len(lines)
            entries = "\n".join(lines[index + 1 : end]).strip("\n")
            if entries:
                merged.setdefault(name, []).append(entries)
    order = [kind for kind in KINDS if kind in merged] + [name for name in merged if name not in KINDS]
    return "\n\n".join(leads + [f"### {name}\n\n" + joined(merged[name]) for name in order])


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
    lines = changelog.split("\n")
    kept = [lines[index] for index, line in enumerate(structure(changelog))
            if not (line.kind == "definition" and LABEL.search(lines[index]).group(1) in labels)]
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
    headings = marks(changelog)
    unreleased = next((at for at, (_, label) in enumerate(headings) if label == "Unreleased"), None)
    if unreleased is None:
        raise SystemExit("CHANGELOG.md has no [Unreleased] section, so there is nothing to close")
    if version in sections(changelog):
        raise SystemExit(f"CHANGELOG.md already has a section for {version}")

    all_lines, kinds = changelog.split("\n"), structure(changelog)
    first = headings[unreleased][0] + 1
    end = headings[unreleased + 1][0] if unreleased + 1 < len(headings) else len(all_lines)
    head = "\n".join(all_lines[:first]) + "\n"
    after = "\n".join(all_lines[end:]) if end < len(all_lines) else ""

    # The lines below [Unreleased]: blank ones and link definitions at their end belong to the file, not the section.
    lines, line_kinds = all_lines[first:end], kinds[first:end]
    foot_lines = []
    while lines and (not lines[-1].strip(" \t\r") or line_kinds[len(lines) - 1].kind == "definition"):
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
    if not entries.strip():
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
    written = head + replacement + after
    return linked(written, repository_url.rstrip("/"), prefix) if repository_url else written
