"""The part of Markdown a changelog needs, read line by line, and a refusal for the rest.

GitHub reads CHANGELOG.md as GitHub Flavored Markdown, CommonMark 0.29 with extensions, in cmark-gfm.
Reading all of that takes a library, and reading it with patterns line by line gets it wrong in silence:
a `## [x]` inside a fenced code block counts as a section, a `- **BREAKING**` inside one as an entry.
So this reads a declared part of it, the way CommonMark reads it, and refuses every line outside that part
with its number and what to write instead. lib/README.md lists both.

Read:
- blank lines and paragraph text, continued lazily as CommonMark continues it;
- ATX headings, outside list items;
- list items, `-`, `*`, `+` or a number with `.` or `)`, nested, and their continuation lines;
- fenced code blocks, at the top or inside a list item;
- HTML comments, `<!--` to the line holding `-->`;
- link reference definitions on one line, outside list items, followed by a blank line or another definition.

The test against cmark-gfm in .github/test_changelog_reader.py holds this to GitHub's reading:
every text read here is split into the same headings, list items and code as cmark-gfm splits it.
"""

import re
import string
from collections.abc import Iterator
from typing import NamedTuple


class Line(NamedTuple):
    """What one line of the text is.

    `kind` is one of:
    - `blank`;
    - `text`: paragraph text, or a paragraph's continuation inside a list item;
    - `heading`: `level` is the number of #s, `text` what follows them, without a closing run of #s;
    - `item`: the line a list item starts on; `level` is how deep the first item it starts is nested, 1 for a list
      at the top, and `text` what follows the last marker on the line: `a` in `- - a`, an item holding an item.
      The line can also open a fenced code block or an HTML comment, whose further lines are `code` or `html`;
    - `code`: a line of a fenced code block, its fences included;
    - `html`: a line of an HTML comment;
    - `definition`: a link reference definition.
    """
    kind: str
    level: int = 0
    text: str = ""


class Unread(Exception):
    """A line outside the part of Markdown read here, by its number from 1, with what to write instead."""

    def __init__(self, number: int, what: str, instead: str):
        # What the line is, without what to write instead: for a text nobody can edit.
        self.found = f"line {number} holds {what}, which lib/main.py does not read"
        super().__init__(f"{self.found}: write {instead}")
        self.number = number


HEADING = re.compile(r"(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")
CLOSING_HASHES = re.compile(r"(?:^|[ \t]+)#+$")
BULLET = re.compile(r"[-*+]")
ORDERED = re.compile(r"(\d{1,9})[.)]")
THEMATIC_BREAK = re.compile(r"([-*_])(?:[ \t]*\1){2,}[ \t]*$")
UNDERLINE = re.compile(r"(?:=+|-+)[ \t]*$")
FENCE = re.compile(r"(`{3,}|~{3,})(.*)$")
# The start of an HTML block of any type but a comment (GitHub Flavored Markdown spec, section 4.6),
# or of inline HTML: a tag, a closing tag, a processing instruction, a declaration or CDATA.
# Inline HTML at the start of a line is refused with the blocks, as telling the two apart is not done here.
# An autolink, `<https://...>`, is neither.
OTHER_HTML = re.compile(r"<(?:[A-Za-z][A-Za-z0-9-]*(?:[ \t/>]|$)|/[A-Za-z]|\?|![A-Za-z]|!\[CDATA\[)")
# The definition of a footnote, which GitHub reads as a block of its own (scan_footnote_definition() in cmark-gfm).
FOOTNOTE = re.compile(r"\[\^[^\] \t\r\n\0]+\]:")
# A table's delimiter row, `--- | ---` or `:-` alone: the line under the header row of a GitHub table.
TABLE_DELIMITER = re.compile(r"\|?[ \t]*:?-+:?[ \t]*(?:\|[ \t]*:?-+:?[ \t]*)*\|?[ \t]*$")


def opening_fence(content: str) -> re.Match | None:
    """The fence `content` opens a fenced code block with, or None.
    A backtick fence's info string cannot hold a backtick: ```x``` is inline code."""
    fence = FENCE.match(content)
    if fence and not (fence.group(1)[0] == "`" and "`" in fence.group(2)):
        return fence
    return None


# How cmark-gfm 0.29.0.gfm.13 reads a link definition, which is how GitHub reads one: cmark_parse_reference_inline()
# in its src/inlines.c, with the scanners it calls, ported line by line but for the title scanner.
# Each reads `text` from `at` and returns where it stopped, or -1 where it found nothing.
# The title is read in one pass and its longest end taken, as the re2c scanner does: a pattern would try a shorter
# title where the longest fails, and backtrack over a title of backslashes for as long as it has them.
# The scanners' checks for U+0000 stay, though none reaches them: reading() reads it as U+FFFD first, as cmark-gfm does.
# cmark_isspace(): space, tab, line feed and carriage return; a form feed or a vertical tab is none there.
SPACE = " \t\n\r"


def spaces_and_a_line_end(text: str, at: int) -> int:
    """spnl(): spaces and tabs, at most one line end, and spaces and tabs again."""
    at = skip_spaces(text, at)
    end = line_end(text, at)
    return skip_spaces(text, end) if end >= 0 else at


def skip_spaces(text: str, at: int) -> int:
    while at < len(text) and text[at] in " \t":
        at += 1
    return at


def line_end(text: str, at: int) -> int:
    """skip_line_end(): past a carriage return, a line feed or both, or at the end of the text; -1 where none
    stands at `at`."""
    start = at
    if text[at:at + 1] == "\r":
        at += 1
    if text[at:at + 1] == "\n":
        at += 1
    return at if at > start or at >= len(text) else -1


def label_end(text: str, at: int) -> int:
    """link_label(): `[`, up to 1000 bytes of UTF-8 with no unescaped bracket and not only spaces, and `]`."""
    if text[at:at + 1] != "[":
        return -1
    start, at, length = at + 1, at + 1, 0
    while at < len(text) and text[at] not in "[]\0":
        if text[at] == "\\" and at + 1 < len(text) and text[at + 1] in string.punctuation:
            at, length = at + 2, length + 2
        else:
            at, length = at + 1, length + len(text[at].encode())
        if length > 1000:  # MAX_LINK_LABEL_LENGTH
            return -1
    if text[at:at + 1] != "]" or not text[start:at].strip(SPACE):
        return -1
    return at + 1


def address_end(text: str, at: int) -> int:
    """manual_scan_link_url(): an address in `<>`, or one without them, which ends at a space or at a `)` that closes
    no `(` before it, and takes no more than 32 `(` open at once."""
    if text[at:at + 1] == "<":
        at += 1
        while at < len(text):
            if text[at] == ">":
                at += 1
                break
            if text[at] == "\\":
                at += 2
            elif text[at] in "\n<":
                return -1
            else:
                at += 1
        return at if at < len(text) else -1
    start, depth = at, 0
    while at < len(text):
        if text[at] == "\\" and at + 1 < len(text) and text[at + 1] in string.punctuation:
            at += 2
        elif text[at] == "(":
            depth, at = depth + 1, at + 1
            if depth > 32:
                return -1
        elif text[at] == ")":
            if depth == 0:
                break
            depth, at = depth - 1, at + 1
        elif text[at] in SPACE:
            if at == start:
                return -1
            break
        else:
            at += 1
    return at if at < len(text) else -1


def title_end(text: str, at: int) -> int:
    """scan_link_title(): a title in `"`, `'` or `()`, where a backslash escapes punctuation or stands for itself,
    ending at the last of its possible ends; -1 where there is none."""
    close = {'"': '"', "'": "'", "(": ")"}.get(text[at:at + 1])
    if close is None:
        return -1
    inside = "()" if close == ")" else close
    reached, end = {at + 1}, -1
    for here in range(at + 1, len(text)):
        if here not in reached:
            continue
        if text[here] == close:
            end = here + 1
        if text[here] == "\\" and here + 1 < len(text) and text[here + 1] in string.punctuation:
            reached.add(here + 2)
        if text[here] not in inside and text[here] != "\0":
            reached.add(here + 1)
    return end


def link_definition(paragraph: str) -> int:
    """Where the link definition `paragraph` starts with ends, its line end included, or 0 where it starts with none.

    `paragraph` ends in a line end, as a paragraph does in cmark-gfm."""
    at = label_end(paragraph, 0)
    if at < 0 or paragraph[at:at + 1] != ":":
        return 0
    at = address_end(paragraph, spaces_and_a_line_end(paragraph, at + 1))
    if at < 0:
        return 0
    before_title = at
    at = spaces_and_a_line_end(paragraph, at)
    title = title_end(paragraph, at) if at != before_title else -1
    end = line_end(paragraph, skip_spaces(paragraph, title if title >= 0 else before_title))
    if end < 0 and title >= 0:  # Text after the title: the line may end before it.
        end = line_end(paragraph, skip_spaces(paragraph, before_title))
    return max(end, 0)


def paragraph_from(content: str, below: list[str]) -> str:
    """`content` and the lines `below` it that go on its paragraph, with their indentation taken off, as CommonMark
    joins them.

    The paragraph ends at a blank line, or at a line that opens a block of its own: a fence, a heading, a block
    quote, HTML, a thematic break or an underline, or a list starting at 1 or with a bullet.
    A line indented by four or more opens none of these, and goes on the paragraph."""
    joined = [content]
    for line in below:
        rest = line.lstrip(" \t")
        if not rest:
            break
        if len(line) - len(rest) < 4 and (
                opening_fence(rest) or HEADING.match(rest) or rest.startswith((">", "<!--"))
                or OTHER_HTML.match(rest) or THEMATIC_BREAK.match(rest) or UNDERLINE.match(rest)
                or re.match(r"(?:[-*+]|0*1[.)])[ \t]+\S", rest)):
            break
        joined.append(rest)
    return "\n".join(joined)


def read(text: str) -> list[Line]:
    """One Line for each line of `text`, split where CommonMark ends a line: at a CRLF, a lone CR or an LF.

    Raises Unread at the first line outside the part of Markdown read here."""
    return list(reading(text))


def reading(text: str) -> Iterator[Line]:
    """The Lines of read(), one at a time: a line is read only when the one before it has been taken.

    A caller that stops early is given no refusal of a line below where it stopped.
    A fenced code block or a comment never closed is refused only once the last line has been taken."""
    # cmark-gfm reads U+0000 as U+FFFD.
    lines = [line.replace("\0", "\ufffd") for line in re.split(r"\r\n|\r|\n", text)]
    previous: str | None = None  # The kind of the line before.
    items: list[int] = []  # The column each open list item's text starts at, the outermost first.
    paragraph: int | None = None  # How many items deep the open paragraph is, or None.
    # CommonMark reads link definitions as a paragraph, and takes them out of it only when it closes:
    # so a definition can be followed by another, but a line of text after one goes on its paragraph.
    definitions = False  # Whether the open paragraph holds nothing but link definitions so far.
    block: tuple | None = None  # An open fence (kind, number, depth, char, length) or comment (kind, number, depth).

    for number, line in enumerate(lines, 1):
        lead = len(line) - len(line.lstrip(" \t"))
        if "\t" in line[:lead]:
            raise Unread(number, "a tab in its indentation", "spaces")
        indent = lead
        blank = not line.strip(" \t")  # A no-break space or a form feed is text to CommonMark.

        if block is not None:
            column = items[block[2] - 1] if block[2] else 0
            if not blank and indent < column:
                what = "a fenced code block" if block[0] == "fence" else "an HTML comment"
                raise Unread(number, f"a line of {what} in a list item left of the item's text",
                             "it indented as far as the item's text")
            if block[0] == "fence":
                previous = "code"
                yield Line("code")
                rest = line[column:]
                if (not blank and indent - column <= 3
                        and re.fullmatch(re.escape(block[3]) + "{%d,}[ \t]*" % block[4], rest.strip(" "))):
                    block = None
            else:
                previous = "html"
                yield Line("html")
                if "-->" in line:
                    block = None
            continue

        if blank:
            previous = "blank"
            yield Line("blank")
            paragraph = None
            continue

        depth = 0
        while depth < len(items) and indent >= items[depth]:
            depth += 1
        position = indent
        line_kind: Line | None = None
        text = False  # Whether the line ends in paragraph text, which opens or continues a paragraph.
        while True:
            column = items[depth - 1] if depth else 0
            content = line[position:]
            relative = position - column
            in_paragraph = paragraph is not None and paragraph == depth
            lazy = paragraph is not None and paragraph > depth

            if relative >= 4:
                if in_paragraph or lazy:
                    text = True
                    break
                raise Unread(number, "an indented code block", "a fenced code block")
            if content.startswith(">"):
                raise Unread(number, "a block quote", "a paragraph or a list item")
            fence = opening_fence(content)
            if fence:
                del items[depth:]
                paragraph = None
                block = ("fence", number, depth, fence.group(1)[0], len(fence.group(1)))
                line_kind = line_kind or Line("code")
                break
            heading = HEADING.match(content)
            if heading:
                if depth:
                    raise Unread(number, "a heading inside a list item", "the heading above the list")
                del items[depth:]
                paragraph = None
                title = CLOSING_HASHES.sub("", (heading.group(2) or "").strip(" \t"))
                line_kind = Line("heading", len(heading.group(1)), title)
                break
            if THEMATIC_BREAK.match(content):
                raise Unread(number, "a thematic break", "a heading, or nothing")
            if UNDERLINE.match(content):
                raise Unread(number, "a line of only = or only -, which can underline a heading",
                             "a heading of #s")
            if TABLE_DELIMITER.match(content):
                raise Unread(number, "the delimiter row of a table", "a list")
            if content.startswith("<!--"):
                del items[depth:]
                paragraph = None
                line_kind = line_kind or Line("html")
                if "-->" not in content[2:]:  # `<!-->` and `<!--->` are comments of their own
                    block = ("comment", number, depth)
                break
            if OTHER_HTML.match(content):
                raise Unread(number, "HTML at its start, other than a comment", "Markdown, or text before the HTML")
            marker = BULLET.match(content) or ORDERED.match(content)
            if marker:
                after = content[marker.end():]
                spaces = len(after) - len(after.lstrip(" "))
                ordered = marker.re is ORDERED
                if after[:1] not in ("", " ", "\t"):
                    marker = None  # `-x` or `1.x` is text
                elif not after.strip(" \t"):
                    raise Unread(number, "an empty list item", "a list item with text")
                elif after[:spaces + 1].endswith("\t"):
                    raise Unread(number, "a tab after a list marker", "a space")
                elif in_paragraph and ordered and int(marker.group(1)) != 1:
                    marker = None  # Only a list starting at 1 interrupts a paragraph.
            if marker:
                if spaces >= 5:
                    raise Unread(number, "an indented code block", "one space after the list marker")
                del items[depth:]
                items.append(position + marker.end() + spaces)
                depth = len(items)
                paragraph = None
                position = items[-1]
                line_kind = Line("item", line_kind.level if line_kind else depth, line[position:])
                continue
            if FOOTNOTE.match(content):
                raise Unread(number, "a footnote definition", "the note in the entry itself")
            # Where a paragraph can start, it can start with a link definition, and how far that goes is read off
            # the whole paragraph: `[a link` can go on as `wrapped](url)`, and `[1.0.0]:` as its address.
            defined = 0
            if content.startswith("[") and not lazy and (not in_paragraph or definitions):
                joined = paragraph_from(content, lines[number:]) + "\n"
                defined = link_definition(joined)
            if defined and depth:
                raise Unread(number, "a link definition inside a list item", "it outside the lists, on one line")
            if defined and "\n" in joined[:defined - 1]:
                raise Unread(number, "a link definition that goes on in the next line", "the definition on one line")
            if defined:
                del items[depth:]
                paragraph, definitions = depth, True
                line_kind = Line("definition")
                break
            text = True
            break

        if previous == "definition" and (line_kind is None or line_kind.kind != "definition"):
            raise Unread(number,
                         "a line right after a link definition, where CommonMark reads some lines as part of it",
                         "a blank line between them")
        if text:
            # An open paragraph goes on, in its own item even where this line is left of that item's text.
            if not (in_paragraph or lazy):
                del items[depth:]
                paragraph = depth
            definitions = False
        line_kind = line_kind or Line("text")
        previous = line_kind.kind
        yield line_kind

    if block is not None:
        what = "a fenced code block" if block[0] == "fence" else "an HTML comment"
        raise Unread(block[1], f"{what} that is never closed", "its closing line")
