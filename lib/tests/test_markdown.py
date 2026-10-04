"""Tests for rules/markdown.py: what it reads in a changelog, and what it refuses, by line.

That what it reads is read as GitHub reads it is .github/test_changelog_reader.py's, against cmark-gfm.

Run with `python3 -m unittest discover -s lib` from the repository root.
"""

import time
import unittest

from rules.markdown import Line, Unread, read


def kinds(text):
    return [line.kind for line in read(text)]


class WhatIsRead(unittest.TestCase):

    def test_headings_items_and_text(self):
        self.assertEqual(read("## [1.0.0] - x ##\n\n- **BREAKING** a\n  more\n  - b\n1. c\n"), [
            Line("heading", 2, "[1.0.0] - x"), Line("blank"), Line("item", 1, "**BREAKING** a"), Line("text"),
            Line("item", 2, "b"), Line("item", 1, "c"), Line("blank")])

    def test_a_fence_is_code_wherever_it_stands(self):
        self.assertEqual(kinds("- a\n\n  ```\n  ## [9.9.9]\n  ```\n```\n- b\n```\n"),
                         ["item", "blank", "code", "code", "code", "code", "code", "code", "blank"])

    def test_three_backticks_with_a_backtick_after_them_are_inline_code(self):
        self.assertEqual(kinds("```x``` is code\n- ```y```\n"), ["text", "item", "blank"])

    def test_a_comment_over_lines_is_not_read(self):
        self.assertEqual(kinds("<!--\n## [9.9.9]\n-->\n- a <!-- b -->\n"), ["html", "html", "html", "item", "blank"])

    def test_lazy_continuation_goes_on_the_item_s_paragraph(self):
        """Even indented by four or more, a line goes on a paragraph rather than opening a code block."""
        self.assertEqual(kinds("- a\nb\n        c\n- d\n"), ["item", "text", "text", "item", "blank"])

    def test_lazy_continuation_of_a_nested_item_is_no_code_block(self):
        """Four spaces past the outer item's text, but left of the nested item's: the nested paragraph goes on."""
        self.assertEqual(kinds("- a\n  -    b\n      c\n"), ["item", "item", "text", "blank"])

    def test_a_fence_indented_by_four_closes_nothing(self):
        self.assertEqual(kinds("```\n    ```\n```\n"), ["code", "code", "code", "blank"])

    def test_only_a_list_starting_at_1_interrupts_text(self):
        self.assertEqual(kinds("Text\n2. two\n1. one\n"), ["text", "text", "item", "blank"])

    def test_a_list_starting_at_01_starts_at_1(self):
        self.assertEqual(kinds("Text\n01. one\n"), ["text", "item", "blank"])

    def test_definitions_follow_each_other(self):
        self.assertEqual(kinds("[a]: https://a\n[b]: https://b 'title'\n\ntext\n[c]: https://c\n"),
                         ["definition", "definition", "blank", "text", "text", "blank"])

    def test_text_that_is_no_link_definition_is_text(self):
        """Each starts as a definition would, and as it stands is none."""
        for text in ("[scope]: entry text\n- [scope]: entry text\n", "[scope]: rename 'a' to b\n",
                     "[scope]: add (optional) flag\n", "[x]: https://a \"t\" junk\n",
                     "- [a link\n  wrapped](https://a) entry\n", "[a link\nwrapped](https://a) text\n",
                     "[x]: https://a 'open\n", "[x]: foo)\n", "[x]: " + "(" * 33 + "a\n",
                     '[x]: <https://a>"t"\n',
                     '[x]: https://a "t\\"\n[y]: https://b "z"\n'):
            with self.subTest(text=text):
                self.assertNotIn("definition", kinds(text))

    def test_a_block_below_ends_the_paragraph_a_definition_can_go_on_in(self):
        """`[x]:` alone is no definition: the fence below opens a block, and is no address."""
        self.assertEqual(kinds("[x]:\n```\ncode\n```\n"), ["text", "code", "code", "code", "blank"])
        self.assertEqual(kinds("[x]:\n- https://a\n"), ["text", "item", "blank"])
        self.assertEqual(kinds("[x]:\n# https://a\n"), ["text", "heading", "blank"])

    def test_escapes_and_parentheses_in_a_definition(self):
        """As cmark-gfm reads them: an escaped quote or parenthesis stays inside a title or an address, a backslash
        can also stand for itself in a title, and an address takes up to 32 `(` open at once."""
        for text in ('[x]: https://a "a \\"b\\" c"\n', "[x]: https://a (a \\) b)\n", "[x]: <https://a\\>b>\n",
                     "[x]: foo(bar\n", "[x]: a\\)b\n", "[x]: f(o)o\n", '[x]: https://a "t\\"\n',
                     "[x]: https://a 't\\'\n", "[x]: " + "(" * 32 + "a\n"):
            with self.subTest(text=text):
                self.assertEqual(kinds(text), ["definition", "blank"])

    def test_a_label_takes_up_to_1000_bytes(self):
        """cmark-gfm counts the label in bytes of UTF-8: 500 `ě` are 1000 of them."""
        for label, kind in (("a" * 1000, "definition"), ("a" * 1001, "text"), ("ě" * 500, "definition"),
                            ("ě" * 501, "text")):
            with self.subTest(length=len(label)):
                self.assertEqual(kinds(f"[{label}]: https://a\n")[0], kind)

    def test_only_spaces_and_tabs_make_a_line_blank(self):
        """A no-break space or a form feed is text to CommonMark.
        The paragraph goes on over it, and `2.` interrupts nothing."""
        for space in ("\u00a0", "\f"):
            with self.subTest(space=repr(space)):
                self.assertEqual(kinds(f"Text\n{space}\n2. x\n"), ["text", "text", "text", "blank"])
        self.assertEqual(kinds("Text\n   \n2. x\n"), ["text", "blank", "item", "blank"])

    def test_a_heading_keeps_a_no_break_space_at_its_end(self):
        self.assertEqual(read("### Added\u00a0\n")[0], Line("heading", 3, "Added\u00a0"))

    def test_a_nul_is_read_as_the_replacement_character(self):
        """cmark-gfm takes U+0000 for U+FFFD, three bytes of UTF-8, and a label goes on over it."""
        self.assertEqual(kinds("[a\0b]: https://a\n"), ["definition", "blank"])
        self.assertEqual(kinds("[" + "\0" * 333 + "]: https://a\n")[0], "definition")
        self.assertEqual(kinds("[" + "\0" * 334 + "]: https://a\n")[0], "text")

    def test_a_title_is_read_in_one_pass(self):
        """A title of 40 `\\a` with no closing quote is read within a second, where a pattern backtracked over it."""
        started = time.monotonic()
        self.assertEqual(kinds('[x]: https://a "' + "\\a" * 40 + "\n"), ["text", "blank"])
        self.assertLess(time.monotonic() - started, 1)

    def test_an_item_s_text_follows_the_last_marker_on_its_line(self):
        self.assertEqual(read("- - **BREAKING** a\n"), [Line("item", 1, "**BREAKING** a"), Line("blank")])

    def test_an_empty_comment_closes_on_its_line(self):
        self.assertEqual(kinds("<!-->\n- a\n<!--->\n- b\n"), ["html", "item", "html", "item", "blank"])

    def test_a_carriage_return_ending_a_line_is_not_part_of_it(self):
        self.assertEqual(read("## [Unreleased]\r\n- a\r\n"), [Line("heading", 2, "[Unreleased]"), Line("item", 1, "a"),
                                                              Line("blank")])

    def test_a_lone_carriage_return_ends_a_line(self):
        """As it does in CommonMark, so that a line number means the line cmark-gfm and an editor count."""
        self.assertEqual(read("## [Unreleased]\r- a\r"), [Line("heading", 2, "[Unreleased]"), Line("item", 1, "a"),
                                                          Line("blank")])


class WhatIsRefused(unittest.TestCase):
    """Each line lib/README.md lists as refused, by its number and with what to write instead."""

    def assert_refused(self, text, number, said):
        with self.assertRaises(Unread) as raised:
            read(text)
        self.assertEqual(raised.exception.number, number)
        self.assertIn(said, str(raised.exception))

    def test_each_refused_line(self):
        for text, number, said in (
                ("Text\n\n    code\n", 3, "an indented code block"),
                ("- a\n\t- b\n", 2, "a tab in its indentation"),
                ("> quoted\n", 1, "a block quote"),
                ("Text\n===\n", 2, "a line of only = or only -"),
                ("Text\n\n***\n", 3, "a thematic break"),
                ("- - -\n", 1, "a thematic break"),
                ("- a\n\n  ## [9.9.9]\n", 3, "a heading inside a list item"),
                ("- # a\n", 1, "a heading inside a list item"),
                ("- a\n-\n", 2, "a line of only = or only -"),
                ("1.\n", 1, "an empty list item"),
                ("<details>\n", 1, "HTML at its start, other than a comment"),
                ("- <kbd>K</kbd> key\n", 1, "HTML at its start, other than a comment"),
                ("- [a]: https://a\n", 1, "a link definition inside a list item"),
                ("[a]: https://a\n  'title'\n", 1, "a link definition that goes on in the next line"),
                ("[a]: https://a\n  'title' and text\n", 2, "a line right after a link definition"),
                ("[a]: https://a\ntext\n", 2, "a line right after a link definition"),
                ("[a]: https://a\n    [b]: https://b\n", 2, "a line right after a link definition"),
                ("[a]:\nhttps://a\n", 1, "a link definition that goes on in the next line"),
                ("[a\nb]: https://a\n", 1, "a link definition that goes on in the next line"),
                ("[a]: https://a 'two\nlines'\n", 1, "a link definition that goes on in the next line"),
                ("[a]:\n<https://a>\n", 1, "a link definition that goes on in the next line"),
                ("[a]:\n    https://a\n", 1, "a link definition that goes on in the next line"),
                ("a | b\n--- | ---\n", 2, "the delimiter row of a table"),
                ("a\n:-\n", 2, "the delimiter row of a table"),
                ("Text.[^1]\n\n[^1]: a note\n", 3, "a footnote definition"),
                ("- [^1]: a note\n", 1, "a footnote definition"),
                ("- [a]: https://a 'two\n  lines'\n", 1, "a link definition inside a list item"),
                ("-\tb\n", 1, "a tab after a list marker"),
                ("~~~\ncode\n", 1, "a fenced code block that is never closed"),
                ("<!--\n- a\n", 1, "an HTML comment that is never closed"),
                ("- a\n\n  ```\nb\n  ```\n", 4, "a line of a fenced code block in a list item left of the item's text"),
                ("-      a\n", 1, "an indented code block")):
            with self.subTest(text=text):
                self.assert_refused(text, number, said)

    def test_the_refusal_says_what_to_write_instead(self):
        self.assert_refused("> q\n", 1, "which lib/main.py does not read: write a paragraph or a list item")

    def test_an_autolink_is_no_html_block(self):
        self.assertEqual(kinds("<https://example.invalid> is the site\n"), ["text", "blank"])


if __name__ == "__main__":
    unittest.main()
