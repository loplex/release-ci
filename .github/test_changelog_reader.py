#!/usr/bin/env python3
"""lib/rules/markdown.py reads every text it accepts the way GitHub does.

Each text the reader accepts is rendered by cmarkgfm, the Python binding of GitHub's own cmark-gfm, with the
source positions of every block, and the two have to agree on which lines are headings and of which level, which
lines start list items, and which lines are code.
A line of text has to stand in one of cmark-gfm's paragraphs or list items, and a line of a comment outside its
paragraphs, headings and code.
A line that starts as a link definition does, `[label]:` and an address, has to be hidden by cmark-gfm where the
reader reads a definition, and shown where it reads text.
The texts are this repository's CHANGELOG.md as it stood at every commit, written cases, and documents put together
at random from lines a changelog could hold.
cmark-gfm passes no raw HTML through here: a comment it passed on as `<!-->` would read to HTMLParser as one still
open, and hide the blocks after it.
It reads footnotes, as GitHub does.

Run with `python3 -m unittest discover -s .github` from the repository's root, with the packages in
`lib/requirements.txt` and `.github/requirements.txt` installed.
"""

import random
import re
import subprocess
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path

import cmarkgfm
from cmarkgfm.cmark import Options

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

from rules.markdown import Unread, opening_fence, read  # noqa: E402


class Blocks(HTMLParser):
    """The lines cmark-gfm gives each kind of block, read off the `data-sourcepos` of its rendered HTML."""

    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.headings, self.items, self.code, self.paragraphs, self.listed = set(), set(), set(), set(), set()
        self.shown, self.in_code = [], 0
        self.feed(cmarkgfm.github_flavored_markdown_to_html(
            text, options=Options.CMARK_OPT_SOURCEPOS | Options.CMARK_OPT_FOOTNOTES))

    def handle_starttag(self, tag, attrs):
        position = dict(attrs).get("data-sourcepos")
        if position is None:
            return
        first, start, last, end = map(int, re.fullmatch(r"(\d+):(\d+)-(\d+):(\d+)", position).groups())
        # A block ending at column 0 of a line ends with the line before it.
        lines = set(range(first, last + (end > 0)))
        if re.fullmatch(r"h[1-6]", tag):
            self.headings.add((first, int(tag[1])))
        elif tag == "li":
            self.items.add(first)
            self.listed |= lines
        elif tag == "pre":
            self.code |= lines
            self.in_code += 1
        elif tag == "p":
            self.paragraphs |= lines

    def handle_endtag(self, tag):
        self.in_code -= tag == "pre"

    def handle_data(self, data):
        if not self.in_code:
            self.shown.append(data)


def disagreements(text):
    """Where the reader and cmark-gfm read `text` differently, or None where the reader refuses it."""
    try:
        lines = read(text)
    except Unread:
        return None
    blocks = Blocks(text)
    numbered = list(enumerate(lines, 1))
    found = []
    headings = {(number, line.level) for number, line in numbered if line.kind == "heading"}
    if headings != blocks.headings:
        found.append(f"headings: read {sorted(headings)}, GitHub {sorted(blocks.headings)}")
    items = {number for number, line in numbered if line.kind == "item"}
    if items != blocks.items:
        found.append(f"list items: read {sorted(items)}, GitHub {sorted(blocks.items)}")
    code = {number for number, line in numbered
            if line.kind == "code" or line.kind == "item" and opening_fence(line.text)}
    if code != blocks.code:
        found.append(f"code: read {sorted(code)}, GitHub {sorted(blocks.code)}")
    text_lines = {number for number, line in numbered if line.kind == "text"}
    if not text_lines <= blocks.paragraphs | blocks.listed:
        outside = sorted(text_lines - blocks.paragraphs - blocks.listed)
        found.append(f"text outside GitHub's paragraphs and items: {outside}")
    # A definition GitHub reads as one is not shown, and one it reads as text is, its address and all.
    # A label can turn into a link on the page, so what is looked for is the address, one of its own on each line.
    shown = "".join(blocks.shown)
    for number, line in numbered:
        source = re.split(r"\r\n|\r|\n", text)[number - 1].strip()
        # Picked by how the line starts, not by what the reader makes of it, so that its reading is compared whole:
        # `[x]: foo)` starts so, and GitHub shows it as text.
        if line.kind in ("text", "definition") and re.match(r"\[(?:\\.|[^\[\]\\])*\]:[ \t]*<?[^\s<>]", source):
            # Shown as text, an escaped character loses its backslash; shown as an autolink, it keeps it.
            address = re.search(r"\]:[ \t]*<?([^\s<>]+)", source).group(1)
            visible = address in shown or re.sub(r"\\(.)", r"\1", address) in shown
            if (line.kind == "definition") == visible:
                seen = "shows" if visible else "hides"
                found.append(f"line {number}: read as {line.kind}, and GitHub {seen} it")
    comments = {number for number, line in numbered if line.kind == "html"}
    inside = comments & (blocks.code | blocks.paragraphs | {number for number, _ in blocks.headings})
    if inside:
        found.append(f"comment lines inside a paragraph, heading or code: {sorted(inside)}")
    return found


# Lines a changelog could hold, and the ones next to them that CommonMark reads otherwise.
PIECES = [
    "", "", "", "# Changelog", "## [Unreleased]", "## [1.0.0] - 2026-10-05", "### Added", "### Fixed ##",
    "Text.", "More text", "  indented text", "    four in", "\\# not a heading", "#hashtag", "####### seven",
    "- entry", "* entry", "+ entry", "- **BREAKING** entry", "1. first", "2. second", "3) third", "10. ten",
    "  - nested", "   - three in", "    - four in", "  1. nested ordered", "- - two on a line", "-x", "1.x",
    "- ```", "```", "```yaml", "~~~", "  ```", "   ~~~", "````", "``` x ```", "use ```x``` inline",
    "<!-- comment -->", "<!--", "-->", "  <!-- in an item -->", "[x]: https://example.invalid/x",
    "[Unreleased]: https://example.invalid/compare/v1...HEAD", "  [y]: https://example.invalid/y",
    "<https://example.invalid> autolink", "- <!-- comment in an item -->", "  text of an item",
    "     five in", "  ## heading in an item", "- [link](https://example.invalid) entry",
    "01. zero one", "<!-->", "<!--->", "[z]:", "https://example.invalid/z", "[open",
    "label]: https://example.invalid/l", "[t]: https://example.invalid/t 'two", "lines'",
    "    [d]: https://example.invalid/d", "a | b", "--- | ---", "|---|---|", "- - ```",
    "[scope]: entry text", "- [scope]: entry text", ":-", "-:", ":--:", "- <!-- c -->", "- - <!-- c -->",
    "[s]: rename 'a' to b", "[s]: add (optional) flag", "- [a link", "  wrapped](https://example.invalid/w) entry",
    "<https://example.invalid/p>", "'a title'", '[e]: https://example.invalid/e "a \\"b\\" c"',
    "[e]: https://example.invalid/e (a \\) b)", '[e]: https://example.invalid/e "t\\"',
    "[f]: https://example.invalid/f)", "[f]: https://example.invalid/f(bar", "[f]: https://example.invalid/f\\)b",
    "[p]: https://example.invalid/" + "(" * 33 + "p", 'some "u" text',
    "[" + "ě" * 500 + "]: https://example.invalid/u", "[" + "ě" * 501 + "]: https://example.invalid/u",
    "[^n]: a note", "Text with a note.[^n]", "[a\\]b]: https://example.invalid/k", "[k]: <>",
    "\u00a0", "\f", "- \u00a0", "[n\0]: https://example.invalid/n", "## \u00a0heading\u00a0",
]


class TheReaderReadsAsGitHubDoes(unittest.TestCase):

    def assert_read_as_github_does(self, text, name):
        self.assertEqual(disagreements(text) or [], [], f"{name}:\n{text}")

    def test_every_changelog_this_repository_had(self):
        shallow = subprocess.run(["git", "rev-parse", "--is-shallow-repository"], cwd=ROOT, check=True,
                                 capture_output=True, text=True).stdout.strip()
        self.assertEqual(shallow, "false", "a shallow clone holds only the last commits: fetch the whole history")
        commits = subprocess.run(["git", "log", "--format=%H", "--", "CHANGELOG.md"], cwd=ROOT, check=True,
                                 capture_output=True, text=True).stdout.split()
        self.assertTrue(commits)
        for commit in commits:
            shown = subprocess.run(["git", "show", f"{commit}:CHANGELOG.md"], cwd=ROOT, capture_output=True, text=True)
            if shown.returncode == 0:
                with self.subTest(commit=commit):
                    self.assertIsNotNone(disagreements(shown.stdout), f"refused at {commit}")
                    self.assert_read_as_github_does(shown.stdout, commit)

    def test_written_cases(self):
        cases = {
            "a fence in an entry":
                "### Fixed\n\n- Use this:\n\n  ```yaml\n  - **BREAKING** x\n  ## [9.9.9]\n  ```\n- next\n",
            "a fence at the top": "## [Unreleased]\n\n```\n## [9.9.9] - x\n- **BREAKING** y\n```\n",
            "a tilde fence closed by a longer one": "~~~\n```\n~~~~\n",
            "inline code of three backticks": "- use ```x``` in a line\n- and ``` alone in the middle\n",
            "lazy continuation": "- a\nb\n  c\n\n- d\n",
            "an ordered list interrupting text": "Text\n1. one\n\nText\n2. two\n",
            "a comment over lines": "<!--\n## [9.9.9]\n- **BREAKING** x\n-->\n- y\n",
            "a comment in an entry": "- a\n  <!-- b -->\n- c\n",
            "definitions at the foot":
                "## [1.0.0] - x\n\n- a\n\n[1.0.0]: https://example.invalid/a\n[x]: <https://example.invalid/b> 't'\n",
            "a fence opened in a nested item on its line": "- - ```\n    x\n    ```\n",
            "a definition after text": "Text\n[x]: https://example.invalid/x\n",
            "headings with closing hashes": "## [1.0.0] - x ##\n### Added #\n#\n",
            "nested lists": "- a\n  - b\n    - c\n  - d\n- e\n",
            "two markers on a line": "- - a\n  - b\n",
            "a CRLF file": "## [Unreleased]\r\n\r\n- a\r\n",
            "a label of a form feed": "[\f]: https://example.invalid/f\n\n[a][\f]\n",
            "a label of a vertical tab": "[\v]: https://example.invalid/v\n\n[a][\v]\n",
            "a form feed in an address": "[a]: https://example.invalid/a\fb\n\n[a]\n",
            "a vertical tab in an address": "[a]: https://example.invalid/a\vb\n\n[a]\n",
            "a label of a tab": "[\t]: https://example.invalid/t\n\n[a][\t]\n",
            "a tab in an address": "[a]: https://example.invalid/a\tb\n\n[a]\n",
            "a label of a carriage return": "[\r]: https://example.invalid/r\n\n[a][\r]\n",
            "a file of lone carriage returns": "## [Unreleased]\r\r- a\r  b\r\r[x]: https://example.invalid/x\r",
        }
        for name, text in cases.items():
            with self.subTest(name):
                self.assertIsNotNone(disagreements(text), f"{name} is refused")
                self.assert_read_as_github_does(text, name)

    def test_documents_put_together_at_random(self):
        chance = random.Random(20261005)
        read_count = 0
        for case in range(5000):
            lines = [chance.choice(PIECES) for _ in range(chance.randint(2, 12))]
            # Each definition an address of its own, so that whether GitHub shows it is told line by line.
            # The address ends in a `-`, so that the one of line 1 is no part of the one of line 10.
            # It goes inside a closing `>`, so that `<https://...>` stays an address.
            text = "\n".join(re.sub(r"(https://example\.invalid/[^\s>]*)", rf"\g<1>-{at}-", line)
                             for at, line in enumerate(lines)) + "\n"
            if disagreements(text) is not None:
                read_count += 1
            with self.subTest(case=case):
                self.assert_read_as_github_does(text, f"document {case}")
        # The comparison means something only where enough of them were read rather than refused.
        self.assertGreater(read_count, 1000)


if __name__ == "__main__":
    unittest.main()
