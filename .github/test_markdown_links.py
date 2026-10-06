#!/usr/bin/env python3
"""Every relative link in a tracked Markdown file reaches a tracked file or directory.
Where it names a heading, the heading exists there.

The Markdown is read by cmarkgfm, the Python binding of GitHub's own cmark-gfm.
So a link, a heading or code is whatever GitHub renders as one.
Run with `python3 -m unittest discover -s .github` from the repository's root,
with the packages in `lib/requirements.txt` and `.github/requirements.txt` installed.
"""

import re
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote

import cmarkgfm
import regex
from cmarkgfm.cmark import Options

ROOT = Path(__file__).resolve().parent.parent


class Rendered(HTMLParser):
    """What the rendered page links to, the text of each of its headings, and the `id` and `name` its tags carry."""

    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.links, self.headings, self.heading, self.ids = [], [], None, set()
        # Unsafe keeps raw HTML a document writes, links included, as GitHub does; nothing here is displayed.
        self.feed(cmarkgfm.github_flavored_markdown_to_html(
            text, options=Options.CMARK_OPT_UNSAFE | Options.CMARK_OPT_FOOTNOTES))

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("a", "img") and (attrs.get("href") or attrs.get("src")):
            self.links.append(attrs.get("href") or attrs.get("src"))
        self.ids.update(attrs[key] for key in ("id", "name") if attrs.get(key))
        if re.fullmatch(r"h[1-6]", tag):
            self.heading = []

    def handle_data(self, data):
        if self.heading is not None:
            self.heading.append(data)

    def handle_endtag(self, tag):
        if re.fullmatch(r"h[1-6]", tag) and self.heading is not None:
            self.headings.append("".join(self.heading))
            self.heading = None


# What a heading's anchor drops, as github.com was seen to drop it: all but `-`, the space and Unicode's word
# characters, the `\w` of UTS #18 Annex C.
DROPPED = regex.compile(r"[^\p{Alphabetic}\p{M}\p{Nd}\p{Pc}\p{Join_Control}\- ]")


def anchors(text):
    """The anchors GitHub gives the headings, with a repeated one numbered from -1.
    cmark-gfm gives headings no anchor; github.com adds them, by this rule:
    - Each character is lower-cased on its own, so a final sigma stays `σ`, where `str.lower()` writes `ς`.
    - Alphabetic characters (letters, letter numbers such as `Ⅻ`, circled letters), marks, decimal numbers,
      connector punctuation, the two joiners, `-` and spaces are kept. Python's `\\w` is not that set: it drops a
      mark (the combining caron of a decomposed `ř`), a circled letter and a joiner, and keeps `²` or `½`.
    - Spaces become hyphens.
    An `id` or a `name` a tag carries is an anchor too, and is where the links of a footnote lead."""
    rendered = Rendered(text)
    seen, found = {}, set(rendered.ids)
    for heading in rendered.headings:
        lowered = "".join(character.lower() for character in heading.strip())
        slug = DROPPED.sub("", lowered).replace(" ", "-")
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        found.add(slug if count == 0 else f"{slug}-{count}")
    return found


def tracked():
    """The files git tracks, and the directories that hold them.
    A link to anything else resolves only on this machine, and breaks in a clone."""
    files = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True,
                           text=True).stdout.split("\0")[:-1]
    return set(files) | {parent.as_posix() for name in files for parent in Path(name).parents}


def broken(path, text, files):
    """The relative links in one file that reach nothing in `files`, or no heading in the Markdown they reach.

    - A link with a scheme (`https:`, `mailto:`) is not a relative one, and is left alone.
    - A link starting with `/` is read from the root of the repository, as GitHub reads it.
    - A heading is looked for in a Markdown file, or in the README.md GitHub shows for a directory.
      The anchor of any other file (`#L10` of a script), or of one shown with a query (`README.md?plain=1#L3`),
      is GitHub's, not a heading's, and is not checked. The query is not part of the path.
    - A link definition nothing uses renders nothing, and is not read."""
    found = []
    for link in Rendered(text).links:
        if re.match(r"[a-z][a-z0-9+.-]*:|//", link, re.I):
            continue
        address, _, fragment = link.partition("#")
        address, query, _ = address.partition("?")
        # Split before decoding, so that an encoded `#` or `?` stays part of a name.
        name, fragment, target = unquote(address), unquote(fragment), unquote(link)
        reached = (ROOT / name.lstrip("/") if name.startswith("/") else path.parent / name).resolve()
        if name and not reached.is_relative_to(ROOT):
            found.append(f"{target}: outside the repository")
            continue
        if name and reached.relative_to(ROOT).as_posix() not in files:
            found.append(f"{target}: no such file")
            continue
        if reached.is_dir() and (reached / "README.md").is_file():
            reached = reached / "README.md"
        if fragment and not query and (not name or reached.suffix == ".md") and fragment not in anchors(
                reached.read_text(encoding="utf-8") if name else text):
            found.append(f"{target}: no such heading")
    return found


class MarkdownLinks(unittest.TestCase):

    def test_every_relative_link_in_a_tracked_file_resolves(self):
        files = tracked()
        names = [name for name in files if name.endswith(".md") and (ROOT / name).is_file()]
        self.assertTrue(names)
        for name in names:
            path = ROOT / name
            self.assertEqual(broken(path, path.read_text(encoding="utf-8"), files), [], name)

    def test_a_missing_file_or_heading_is_found(self):
        text = ("# Here\n\n[a](nowhere.md) [b](README.md#nowhere) [c](#nowhere) [d](#here)\n"
                "[e](.github/test_markdown_links.py) [g](gone.md#x) [f] ![h](gone.png)\n\n[f]: gone.md\n\n"
                "<a href='raw.md'>i</a> [j](mailto:someone@example.com) [k](https://example.com/nowhere.md)\n")
        self.assertEqual(broken(ROOT / "probe.md", text, tracked()), [
            "nowhere.md: no such file", "README.md#nowhere: no such heading", "#nowhere: no such heading",
            "gone.md#x: no such file", "gone.md: no such file", "gone.png: no such file",
            "raw.md: no such file"])

    def test_a_file_git_does_not_track_is_no_target(self):
        """A file on disk that git does not track, such as an ignored or excluded one, is not in a clone."""
        text = "[a](README.md) [b](CONTRIBUTING.md) [c](.github)\n"
        self.assertEqual(broken(ROOT / "probe.md", text, {"README.md", ".github"}), ["CONTRIBUTING.md: no such file"])

    def test_the_root_is_a_target_and_what_is_outside_it_is_not(self):
        text = "[a](./) [b](/README.md#pinning) [c](../elsewhere.md) [d](/nowhere.md)\n"
        self.assertEqual(broken(ROOT / "check-release" / "probe.md", text, tracked()),
                         ["../elsewhere.md: no such file", "/nowhere.md: no such file"])
        self.assertEqual(broken(ROOT / "probe.md", "[e](../elsewhere.md)\n", tracked()),
                         ["../elsewhere.md: outside the repository"])
        self.assertEqual(broken(ROOT / "probe.md", "[f](./) [g](.)\n", {"README.md"}), ["./: no such file",
                                                                                     ".: no such file"])
        self.assertEqual(broken(ROOT / "probe.md", "[f](./) [g](.)\n", tracked()), [])

    def test_a_directory_holding_a_tracked_file_is_a_target(self):
        files = tracked()
        self.assertTrue({"README.md", ".github/test_markdown_links.py", ".github", "release-flow/merge-back", "."}
                        <= files)

    def test_an_anchor_into_a_directory_is_looked_for_in_its_readme(self):
        text = "[a](release-flow#release-flowwarn) [b](./#pinning) [c](release-flow#nowhere) [d](.github#x)\n"
        self.assertEqual(broken(ROOT / "probe.md", text, tracked()), ["release-flow#nowhere: no such heading"])

    def test_an_anchor_into_a_file_that_is_not_markdown_is_not_looked_at(self):
        self.assertEqual(broken(ROOT / "probe.md", "[a](.editorconfig#L2)\n", tracked()), [])

    def test_a_query_is_no_part_of_the_path_and_its_anchor_is_not_looked_at(self):
        text = "[a](README.md?plain=1#L3) [b](gone.md?plain=1)\n"
        self.assertEqual(broken(ROOT / "probe.md", text, tracked()), ["gone.md?plain=1: no such file"])

    def test_a_link_is_split_before_it_is_decoded_and_decoded_once(self):
        """An encoded `#` is part of the name, and `&amp;copy` is `&copy`, not `©`."""
        text = "[a](README.md%23pinning) [b](a&amp;copy.md)\n"
        self.assertEqual(broken(ROOT / "probe.md", text, tracked()),
                         ["README.md#pinning: no such file", "a&copy.md: no such file"])

    def test_a_footnote_an_id_and_a_name_are_targets(self):
        text = 'Claim[^1].\n\n<h2 id="own">Raw</h2>\n\n<a name="n"></a>[a](#own) [b](#n)\n\n[^1]: note\n'
        self.assertEqual(broken(ROOT / "probe.md", text, tracked()), [])

    def test_a_link_with_a_title_or_in_angle_brackets_is_read(self):
        text = ('[a](nowhere.md "a title") [b](<no where.md>) [c](none.md \'t\') [d](gone.md (t))\n'
                '[e](README.md "fine") [f](<README.md>) [g](missing(1).md) [h] [i]\n\n'
                '   [h]: <away.md> "t"\n[i]: README.md \'fine\'\n')
        self.assertEqual(broken(ROOT / "probe.md", text, tracked()), [
            "nowhere.md: no such file", "no where.md: no such file", "none.md: no such file",
            "gone.md: no such file", "missing(1).md: no such file", "away.md: no such file"])

    def test_code_is_not_read_for_links(self):
        self.assertEqual(broken(ROOT / "probe.md", "``` `code` in prose [f](nowhere.md)\n", tracked()),
                         ["nowhere.md: no such file"])
        text = ("`[a](nowhere.md)`\n\n```\n[b](nowhere.md)\n```\n\n~~~\n[c](nowhere.md)\n~~~\n\n"
                "```\n```yaml\n[d](nowhere.md)\n    ```\n[e](nowhere.md)\n```\n\n"
                "``[f](nowhere.md)``\n\n    [g](nowhere.md)\n")
        self.assertEqual(broken(ROOT / "probe.md", text, tracked()), [])

    def test_an_anchor_is_the_one_github_gives(self):
        text = ("# release-flow/merge-back\n## `fetch-depth: 0` is not optional\n## Twice\n## Twice\n"
                "```\n# not a heading\n```\n\nSetext heading\n--------------\n")
        self.assertEqual(anchors(text), {"release-flowmerge-back", "fetch-depth-0-is-not-optional", "twice",
                                         "twice-1", "setext-heading"})

    def test_an_anchor_keeps_what_github_keeps_outside_ascii(self):
        # Each heading beside the anchor github.com gave it (2026-10-01; the word joiner 2026-10-03).
        headings = {
            "Pr\u030cehled": "pr\u030cehled",  # a decomposed ř: the mark stays
            "P\u0159ehled": "p\u0159ehled",
            "\u0158\u00edzen\u00ed": "\u0159\u00edzen\u00ed",
            "\u0130stanbul": "i\u0307stanbul",  # lower-casing İ writes a mark, which stays too
            "\u0939\u093f\u0902\u0926\u0940": "\u0939\u093f\u0902\u0926\u0940",
            "x\u00b2 and \u00bd": "x-and-",  # other numbers go
            "\u216b": "\u217b",  # a letter number stays
            "a\u203fb": "a\u203fb",  # connector punctuation stays
            "\u03a3\u0391\u03a3": "\u03c3\u03b1\u03c3",  # no final sigma
            "a\u20ddb": "a\u20ddb",  # an enclosing mark stays
            "\u24b6": "\u24d0",  # a circled letter is alphabetic, and stays
            "a\u200db": "a\u200db",  # so do the zero-width joiner
            "a\u200cb": "a\u200cb",  # and non-joiner
            "a\u2060b": "ab",  # where the word joiner, a format character too, goes
        }
        self.assertEqual(anchors("".join(f"## {heading}\n" for heading in headings)), set(headings.values()))


if __name__ == "__main__":
    unittest.main()
