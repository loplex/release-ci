"""CHANGELOG.md in the Keep a Changelog format: its sections, closing `[Unreleased]`, and its links.

Plain functions over the file's text, with no repository behind them.
"""

import html
import re
import urllib.parse

from .markdown import Line, Unread, read, reading
from .versions import SEMVER, precedence


# A section's heading is a `##` heading whose text starts with its label in brackets: `## [1.0.0] - 2026-10-05`.
LABEL = re.compile(r"\[([^\]]+)\]")
# Text in brackets, escaped brackets in it included, as a link label stands: `[1]` and `[the issue]` in
# `[the issue][1]`. CommonMark allows no other bracket inside a label.
BRACKETED = re.compile(r"\[((?:\\.|[^\[\]\\])*)\]")

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


# The first list marker on an item's line, and the spaces up to that item's text.
FIRST_ITEM = re.compile(r" *(?:[-*+]|\d{1,9}[.)]) *")
# An HTML comment closed on its line.
COMMENT = re.compile(r"<!--.*?-->")
# An HTML comment left open where an item's text starts, past its list markers, which hides the rest of the line.
OPEN_COMMENT = re.compile(r"((?: *(?:[-*+]|\d{1,9}[.)]) +)* *)<!--")
# An inline link, whose text alone is shown, and not an image: `[text](destination "title")`.
LINK = re.compile(r"(?<!!)\[([^\]]*)\]\([^)]*\)")
# The marks of emphasis and strikethrough.
EMPHASIS = re.compile(r"[*_~]")


def uncommented(lines: list[str], kinds: list[Line]) -> list[str]:
    """The lines with each HTML comment on them blanked out by spaces where it stood, since GitHub shows none.

    A comment is read on its own line only, and the lines it runs on over are read as they are written.
    One left open hides the rest of its line where it starts an item's text, closed comments before it aside, as a
    browser hides it; elsewhere it is text, as GitHub shows it.
    The spaces keep each character that is left in its column."""
    def blank(line: str, kind: Line) -> str:
        line = COMMENT.sub(lambda comment: " " * len(comment[0]), line)
        start = OPEN_COMMENT.match(line) if kind.kind == "item" else None
        return line[: start.end(1)] + " " * (len(line) - start.end(1)) if start else line

    return [blank(line, kind) for line, kind in zip(lines, kinds)]


def closing(line: str) -> str:
    """What a line of an HTML comment holds after the comment closes on it: ` gone` in `<!-- see below --> gone`, and
    nothing where it does not close.
    That is raw HTML, which GitHub passes on as written: its Markdown is not read, a comment in it is left out, one
    left open hides the rest of the line, and a character reference such as `&nbsp;` stands for its character.
    A browser reads more of HTML than this, so closed() refuses such text rather than leave it out with its group."""
    _, end, rest = line.partition("-->")
    return html.unescape(COMMENT.sub("", rest).partition("<!--")[0]) if end else ""


def shown(text: str) -> str:
    """Text whose comments uncommented() has already blanked out, read a little closer to how GitHub shows it.

    A link stands for its text, every `*`, `_` and `~` goes, as the marks of emphasis and strikethrough would, and a
    character reference such as `&nbsp;` stands for its character.
    It is no renderer, so it can differ from GitHub either way: a code span is taken as written, an HTML tag as text,
    and a `*`, `_` or `~` GitHub would show is dropped all the same."""
    return html.unescape(EMPHASIS.sub("", LINK.sub(r"\1", text)))


def item_says_something(lines: list[str], seen: list[str], kinds: list[Line], index: int,
                        innermost: bool = False) -> bool:
    """Whether the items line `index` opens say something, on that line or in the text right below it.

    `seen` holds the lines as uncommented() gives them.
    What is read is the text after the last marker on the line, and the lines of text right below it that are indented
    at least as far as the text of the first item: in `- - <!-- c -->`, two spaces for the outer item, four for the
    inner one.
    With `innermost`, only the last item on the line is asked about, and the lines below are measured from its text.
    Any other line ends what is read, such as a blank line, a comment, a code block or a nested item, and so does a line
    indented less: an item whose text stands only past it says nothing here, though GitHub may show that text."""
    first = FIRST_ITEM.match(lines[index])
    own = len(lines[index]) - len(kinds[index].text)
    start = own if innermost or first is None else first.end()
    read = [seen[index][own:]]
    for below, look, line in zip(lines[index + 1 :], seen[index + 1 :], kinds[index + 1 :]):
        if line.kind != "text" or len(below) - len(below.lstrip(" ")) < start:
            break
        read.append(look)
    return says_something(shown("\n".join(read)))


def silent(text: str) -> list[bool]:
    """Which lines of a section's text say nothing, HTML comments counting as nothing (see uncommented()).

    - A blank line, and a line of a comment, but for what follows the comment where it closes (see closing()).
    - An entry holding nothing but a comment, such as `- <!-- what changed -->` left as a reminder.
    - An entry or a line of text that says nothing else (see shown() and says_something()), such as a no-break space.
    - A link definition, which GitHub shows nowhere, such as `[//]: # (nothing removed yet)`.
    An entry that says something only in the text right below its line says something: see item_says_something().
    A heading and a line of a fenced code block say something, a comment in the code included."""
    lines, kinds = text.split("\n"), structure(text)
    seen = uncommented(lines, kinds)
    return [line.kind in ("blank", "definition")
            or line.kind == "html" and not says_something(closing(lines[index]))
            or line.kind == "item" and not item_says_something(lines, seen, kinds, index)
            or line.kind == "text" and not says_something(shown(seen[index]))
            for index, line in enumerate(kinds)]


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


def matched(label: str) -> str:
    """A link label as cmark-gfm matches it to a definition: case folded, its runs of spaces, tabs and line ends made
    one space, and none at its ends. A no-break space is no white space there."""
    return re.sub(r"[ \t\r\n]+", " ", label).strip(" ").casefold()


def referenced(changelog: str, text: str) -> list[str]:
    """The changelog's link definitions whose label `text` names in brackets, wherever they stand, in the file's order.
    bodies() leaves them out of a section, so the section alone would show `[the issue][1]` as written.
    Any text in brackets counts, so a definition can be named by chance, such as `[0.2.0]` for a version the text
    mentions; GitHub shows no definition, so one too many changes nothing but that bracket."""
    named = {matched(found) for found in BRACKETED.findall(text)}
    lines = changelog.split("\n")
    return [lines[index] for index, line in enumerate(structure(changelog))
            if line.kind == "definition" and matched(BRACKETED.match(lines[index].lstrip(" ")).group(1)) in named]


# A link or an image as cmark-gfm renders one: `<a href="…"` or `<img src="…"`.
# Raw HTML is left out of what it renders, and it escapes `"` and `<` everywhere else, so every match is one it wrote.
RENDERED_LINK = re.compile(r'<(a href|img src)="([^"]*)"')


def absolute_links(rendered: str, repository_url: str, ref: str) -> tuple[str, list[str]]:
    """Rendered notes with every relative link made absolute, read as CHANGELOG.md's own at `ref`, a tag or a commit.

    The notes are shown away from the repository, as a JetBrains plugin's change notes, where a relative link has
    nothing to lead to. They point where GitHub points them on a published release's page:
    - a path to the file at `ref`, `<repository>/blob/<ref>/<path>`, and an image to `/raw/` in place of `/blob/`;
    - one starting with `/` from the repository's root, which is CHANGELOG.md's directory anyway;
    - one that comes to the root itself, such as `./`, to the tree at `ref`.
    Unlike there, `#anchor` alone leads into CHANGELOG.md, where the heading it names stands; on the release page it
    stays an anchor of the page itself.
    A link with a scheme or a host is left as it is.
    One that climbs above the repository's root leads nowhere, on the release page too, and is refused."""
    base = repository_url.rstrip("/")
    at = urllib.parse.quote(ref, safe="/+")
    refused = []

    def absolute(match: re.Match) -> str:
        attribute, written = match.groups()
        target = urllib.parse.urlsplit(html.unescape(written))
        if target.scheme or target.netloc:
            return match.group(0)
        segments = []
        for segment in target.path.split("/"):
            if segment == "..":
                if not segments:
                    refused.append(f"CHANGELOG.md links to {html.unescape(written)}, above the repository's root: "
                                   "the link leads nowhere, here or on the release page")
                    return match.group(0)
                segments.pop()
            elif segment not in ("", "."):
                segments.append(segment)
        if not target.path:
            url = f"{base}/blob/{at}/CHANGELOG.md"
        elif not segments:
            url = f"{base}/tree/{at}"
        else:
            url = f"{base}/{'raw' if attribute == 'img src' else 'blob'}/{at}/{'/'.join(segments)}"
        url += (f"?{target.query}" if target.query else "") + (f"#{target.fragment}" if target.fragment else "")
        return f'<{attribute}="{html.escape(url)}"'

    return RENDERED_LINK.sub(absolute, rendered), refused


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


def pruned(text: str) -> str:
    """A section's text without the `###` groups that say nothing, comments counting as nothing (see silent()).

    A release page would show such a group as a heading with nothing under it.
    The Gradle changelog plugin leaves all six kinds in `[Unreleased]` after a release, with nothing under them.
    A comment under it goes with it: GitHub shows none.
    A link definition under it stays where the group stood, set off by blank lines, since a link elsewhere may use
    it."""
    lines, kinds, quiet, headings = text.split("\n"), structure(text), silent(text), groups(text)
    kept, done = [], 0
    for at, (index, _) in enumerate(headings):
        end = headings[at + 1][0] if at + 1 < len(headings) else len(lines)
        if all(quiet[index + 1 : end]):
            kept += lines[done:index]
            definitions = [lines[line] for line in range(index + 1, end) if kinds[line].kind == "definition"]
            if definitions:
                kept += ([""] if kept and kept[-1].strip(" \t\r") else []) + definitions + [""]
            done = end
    return "\n".join(kept + lines[done:]).strip("\n")


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
    - an `[Unreleased]` that says nothing, comments aside (see silent()): a release with nothing to say, and every
      later check would compare against that;
    - an entry under it that says nothing, comments aside, on its line or in the lines of text right below it, indented
      as far as its text (see item_says_something()), such as `- <!-- what changed -->` left as a reminder: the release
      notes would show an empty bullet.
      Any other line ends what is read, such as a blank line, a comment, a code block or a nested entry, and so does a
      line indented less: an entry whose text stands only past it is refused as well, though GitHub may show that text.
      Of several entries opened on one line, as in `- - <!-- c -->`, the last is the one asked about.
    - text read as saying nothing, comments aside, in a group of `[Unreleased]` that holds nothing else but comments and
      link definitions, a comment's line with something after its `-->` included: the group would be left out (see
      below), and the text with it, which the reading here may have got wrong.
      It is refused even where the entries of a pre-release taken in would keep the group.

    Markdown is read only this far, not rendered (see shown()), so the verdict can differ from GitHub's either way: an
    `[Unreleased]` or an entry left empty by an HTML tag with nothing in it, or by a comment that runs on over lines,
    can pass, and an entry of nothing but `*` is refused.

    A group that says nothing is left out of the section instead (see pruned()): an empty heading names no change.
    An `[Unreleased]` of nothing but such groups is then refused as saying nothing.

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
    seen = uncommented(lines, line_kinds)
    for index, line in enumerate(line_kinds):
        if line.kind == "item" and not item_says_something(lines, seen, line_kinds, index, innermost=True):
            raise SystemExit(f"CHANGELOG.md line {first + index + 1} holds an entry that says nothing, comments aside: "
                             f"write what changed on its line, or take the entry out. Only its line and the lines of "
                             f"text right below it, indented as far as its text, are read")
    foot_lines = []
    while lines and (not lines[-1].strip(" \t\r") or line_kinds[len(lines) - 1].kind == "definition"):
        foot_lines.insert(0, lines.pop())
    # Read once the foot is off: a definition there is no part of the last group, which is left out without it.
    quiet, headings = silent("\n".join(lines)), groups("\n".join(lines))
    for at, (index, name) in enumerate(headings):
        end = headings[at + 1][0] if at + 1 < len(headings) else len(lines)
        text = next((line for line in range(index + 1, end) if line_kinds[line].kind == "text"
                     or line_kinds[line].kind == "html" and lines[line].partition("-->")[2].strip(" \t")), None)
        if all(quiet[index + 1 : end]) and text is not None:
            raise SystemExit(f"CHANGELOG.md line {first + text + 1} holds text read as saying nothing, comments aside, "
                             f"in a ### {name} group that holds nothing else, so it would be left out with the group: "
                             f"write what changed there as an entry, or take the text out")

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
    entries = pruned(entries)
    if all(silent(entries)):
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
    # A blank line of spaces is written empty, so it cannot stand as a foot of its own.
    foot = "\n".join(line if line.strip(" \t\r") else "" for line in foot_lines).strip("\n")
    replacement = f"\n## [{version}] - {on}\n\n{entries}\n"
    if foot:
        replacement += f"\n{foot}\n"
    if after:
        replacement += "\n"
    written = head + replacement + after
    return linked(written, repository_url.rstrip("/"), prefix) if repository_url else written
