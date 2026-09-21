#!/usr/bin/env python3
"""The adapters in sources.py: what every one of them has to answer, and what the Gradle one does to its file.

All of it over text, the adapters being plain objects over text - the file they name is check-release.py's to
read and write, and test_check_release.py exercises that.

Run with `python3 -m unittest discover` over the directory this file sits in.
"""

import importlib.util
import unittest
from pathlib import Path

import sources

SCRIPT = Path(__file__).resolve().parent / "check-release.py"
specification = importlib.util.spec_from_file_location("check_release", SCRIPT)
check_release = importlib.util.module_from_spec(specification)
specification.loader.exec_module(check_release)

GRADLE_PROPERTIES = sources.SOURCES["gradle.properties"]

# A file each source that declares a version would be handed, marked the way it is between releases. A new
# source has to add one here, and test_every_declaring_source_has_a_file_to_be_tried_on says so if it does not.
FILES_TO_TRY_ON = {
    "gradle.properties": "group = cz.loplex\nversion = 0.1.1-SNAPSHOT\ntagPrefix = v\n",
}


class WhatEverySourceAnswers(unittest.TestCase):
    """The contract check-release.py relies on, asked of every adapter filed in SOURCES."""

    def test_every_source_is_filed_under_the_name_it_answers_to(self):
        for name, adapter in sources.SOURCES.items():
            self.assertEqual(adapter.name, name)

    def test_a_marker_is_one_the_rules_refuse_to_release(self):
        """The marker is the adapter's spelling; refusing it is the rules'. A marker they did not refuse would
        let a version being worked on be released."""
        for adapter in sources.SOURCES.values():
            with self.subTest(adapter.name):
                if adapter.marker:
                    marked = f"1.0.0{adapter.marker}"
                    self.assertTrue(check_release.SEMVER.match(marked), f"{marked} is no version the rules read")
                    self.assertTrue(check_release.being_worked_on(marked))
                    self.assertIn("being worked on", " ".join(check_release.check_version(marked, [])))

    def test_a_source_declaring_nothing_names_no_file_and_no_marker(self):
        for adapter in sources.SOURCES.values():
            if not adapter.declares_a_version:
                with self.subTest(adapter.name):
                    self.assertIsNone(adapter.file)
                    self.assertEqual(adapter.marker, "")

    def test_a_source_declaring_a_version_names_its_file_and_what_it_is_looked_in_for(self):
        """check-release.py reads the file and, where it is missing, refuses with what it was looked in for.
        An adapter lacking either is a traceback on its first run rather than a refusal."""
        for adapter in sources.SOURCES.values():
            if adapter.declares_a_version:
                with self.subTest(adapter.name):
                    self.assertTrue(getattr(adapter, "file", None))
                    self.assertTrue(getattr(adapter, "holds", None))

    def test_a_source_declaring_a_version_says_how_its_file_is_read_and_written(self):
        """check-release.py opens the file in the encoding the adapter names, reading it and writing it back, so
        the name has to be a text encoding: open() refuses a codec Python has but that does not turn bytes into
        text, such as `base64`. An adapter with no encoding, or with one of those, is a traceback on its first run
        rather than a refusal, and one naming None is quieter still: open() takes the locale's encoding instead."""
        for adapter in sources.SOURCES.values():
            if adapter.declares_a_version:
                with self.subTest(adapter.name):
                    self.assertTrue(getattr(adapter, "encoding", None))
                    "".encode(adapter.encoding)

    def test_every_declaring_source_has_a_file_to_be_tried_on(self):
        declaring = {name for name, adapter in sources.SOURCES.items() if adapter.declares_a_version}
        self.assertEqual(declaring, set(FILES_TO_TRY_ON))

    def test_what_is_written_is_what_is_read_back(self):
        """The reader and the writer of one file have to agree about how the line is written, or the writing
        stops while the reading goes on working - the half nothing notices."""
        for name, text in FILES_TO_TRY_ON.items():
            with self.subTest(name):
                adapter = sources.SOURCES[name]
                self.assertTrue(adapter.version(text).endswith(adapter.marker))
                self.assertEqual(adapter.version(adapter.with_version(text, "0.1.1")), "0.1.1")

    def test_writing_the_version_leaves_the_prefix_as_it_was(self):
        for name, text in FILES_TO_TRY_ON.items():
            with self.subTest(name):
                adapter = sources.SOURCES[name]
                self.assertEqual(adapter.tag_prefix(adapter.with_version(text, "0.1.1")), adapter.tag_prefix(text))


class RewritingGradleProperties(unittest.TestCase):
    """What a release does to gradle.properties, before it builds and again once it is out. Here rather than
    in a pattern in a workflow, because a reader and a writer that have to agree about how the line is written
    can drift apart in silence: the reading goes on working and only the writing stops, which is the half
    nothing notices."""

    TIGHT = "group=cz.loplex\nversion=0.1.1-SNAPSHOT\ntagPrefix=v\n"
    SPACED = "group = cz.loplex\nversion = 0.2.1-SNAPSHOT\ntagPrefix =\n"

    def test_a_tight_separator_stays_tight(self):
        self.assertIn("version=0.1.1\n", GRADLE_PROPERTIES.with_version(self.TIGHT, "0.1.1"))

    def test_a_spaced_separator_stays_spaced(self):
        self.assertIn("version = 0.2.1\n", GRADLE_PROPERTIES.with_version(self.SPACED, "0.2.1"))

    def test_nothing_but_the_version_line_moves(self):
        """Comments and blank lines included: a real gradle.properties carries both, and a writer dropping them
        would put a change nobody made into the release commit."""
        text = "# the build\n\n" + self.SPACED
        self.assertEqual(GRADLE_PROPERTIES.with_version(text, "0.2.1"), text.replace("0.2.1-SNAPSHOT", "0.2.1"))

    def test_a_key_that_merely_ends_in_version_is_left_alone(self):
        """Spelled the way gradle.properties really spells it. A fixture that differed in case as well -
        `pluginVersion` - would pass under a writer that matched the end of the key rather than the whole of it,
        having never matched either way. Asked alone first: beside a real `version` line, a writer taking both is
        refused for declaring the version twice, and the test would fail on that refusal rather than on the key
        being rewritten."""
        with self.assertRaises(SystemExit):
            GRADLE_PROPERTIES.with_version("plugin.version = 9.9.9\n", "0.2.0")
        text = "plugin.version = 9.9.9\nversion = 0.1.0\n"
        written = GRADLE_PROPERTIES.with_version(text, "0.2.0")
        self.assertIn("plugin.version = 9.9.9\n", written)
        self.assertIn("version = 0.2.0\n", written)

    def test_an_indented_declaration_is_rewritten_where_it_is_read(self):
        """properties() reads past the white space in front of a key, as Gradle does, so an indented declaration
        is one both of them take, and rewritten it keeps its indentation and its separator: either one
        changed would be a change nobody made."""
        self.assertEqual(GRADLE_PROPERTIES.with_version("\tversion = 0.1.0\n", "0.2.0"), "\tversion = 0.2.0\n")
        self.assertEqual(GRADLE_PROPERTIES.with_version("\tversion=0.1.0\n", "0.2.0"), "\tversion=0.2.0\n")

    def test_the_version_is_written_as_data(self):
        """`&` and a backreference are characters in a version, not instructions. They would not be under sed
        or under a regular expression's own substitution, which is half of why this is neither."""
        written = GRADLE_PROPERTIES.with_version(self.SPACED, "1.0.0-a&b\\1")
        self.assertIn("version = 1.0.0-a&b\\\\1\n", written)
        self.assertEqual(GRADLE_PROPERTIES.version(written), "1.0.0-a&b\\1")

    def test_a_file_naming_no_version_is_refused_rather_than_left_as_it_was(self):
        with self.assertRaises(SystemExit):
            GRADLE_PROPERTIES.with_version("group = cz.loplex\n", "0.2.1")

    def test_a_version_declared_twice_is_refused_rather_than_rewritten_once(self):
        """Gradle takes the last declaration, so a writer rewriting the first would leave the build on the
        version it was asked to replace."""
        with self.assertRaises(SystemExit):
            GRADLE_PROPERTIES.with_version("version = 0.1.1-SNAPSHOT\nversion = 0.1.1-SNAPSHOT\n", "0.1.1")

    def test_a_declaration_continued_onto_the_next_line_is_rewritten_whole(self):
        written = GRADLE_PROPERTIES.with_version("a=1\nversion = 0.1.\\\n  1-SNAPSHOT\nb=2\n", "0.1.1")
        self.assertEqual(written, "a=1\nversion = 0.1.1\nb=2\n")

    def test_a_colon_separator_stays_a_colon(self):
        self.assertEqual(GRADLE_PROPERTIES.with_version("version: 0.1.1-SNAPSHOT\n", "0.1.1"), "version: 0.1.1\n")

    def test_a_key_a_continuation_splits_is_written_whole(self):
        """Gradle joins `ver\\` and `sion` into one key, so the version is read there; the first line then holds
        only part of the key, and putting it back would leave the file declaring `ver` instead."""
        written = GRADLE_PROPERTIES.with_version("\tver\\\n  sion = 0.1.0\ntagPrefix = v\n", "0.2.0")
        self.assertEqual(written, "\tversion = 0.2.0\ntagPrefix = v\n")

    def test_the_version_is_escaped_as_properties_store_escapes_a_value(self):
        """Written as data, a version still has to be read back as it was given: a character below a space or
        above `~`, in Latin-1 or outside it, a leading space, and one the format reads as a separator or a comment
        are escaped as Properties.store(OutputStream) escapes them."""
        given = " 1=2:3#4!5\t6\u20ac 7\x01\u00e9\U0001F600"
        written = GRADLE_PROPERTIES.with_version("version = 0.1.0\n", given)
        self.assertEqual(written, "version = \\ 1\\=2\\:3\\#4\\!5\\t6\\u20AC 7\\u0001\\u00E9\\uD83D\\uDE00\n")
        self.assertEqual(GRADLE_PROPERTIES.version(written), given)


class ReadingGradleProperties(unittest.TestCase):
    """gradle.properties is where a release reads the version it is asked to be and the name its tag will
    carry. Gradle accepts spaces around the `=` and projects use both spellings, so a reader that knows only
    one of them reports a file that declares nothing when it declares it the other way."""

    def test_a_declaration_written_tight_is_read(self):
        self.assertEqual(GRADLE_PROPERTIES.version("version=0.2.1-SNAPSHOT\n"), "0.2.1-SNAPSHOT")

    def test_a_declaration_written_with_spaces_is_read(self):
        self.assertEqual(GRADLE_PROPERTIES.version("version = 0.2.1-SNAPSHOT\n"), "0.2.1-SNAPSHOT")

    def test_a_file_naming_no_version_is_refused(self):
        with self.assertRaises(SystemExit):
            GRADLE_PROPERTIES.version("group = cz.loplex\n")

    def test_a_prefix_declared_empty_is_not_a_prefix_left_out(self):
        """The distinction the whole parametrisation rests on: a project that tags bare versions says so, and
        is not to be confused with one that forgot to say anything."""
        self.assertEqual(GRADLE_PROPERTIES.tag_prefix("tagPrefix =\n"), "")
        with self.assertRaises(SystemExit):
            GRADLE_PROPERTIES.tag_prefix("version = 1.0.0\n")

    def test_a_file_that_says_nothing_about_the_prefix_is_refused(self):
        """No default, because the wrong guess passes: a repository tagging bare versions, read as tagging `v*`,
        turns up no released tags at all and every check over them then passes having compared nothing."""
        with self.assertRaises(SystemExit):
            GRADLE_PROPERTIES.tag_prefix("version = 1.0.0\n")

    def test_a_line_continued_onto_the_next_is_one_declaration(self):
        """Gradle reads a line ending in a backslash as going on in the next, so the `version` below is part of
        the jvmargs value and declares nothing: a reader taking it would release a version the build never sees."""
        found = GRADLE_PROPERTIES.properties("org.gradle.jvmargs=-Xmx1g \\\n    version = 0.1.0\ntagPrefix = v\n")
        self.assertEqual(found, {"org.gradle.jvmargs": "-Xmx1g version = 0.1.0", "tagPrefix": "v"})

    def test_an_even_run_of_backslashes_ends_the_line(self):
        found = GRADLE_PROPERTIES.properties("path = C:\\\\dir\\\\\nversion = 1.0.0\n")
        self.assertEqual(found, {"path": "C:\\dir\\", "version": "1.0.0"})

    def test_an_escape_is_read_as_what_it_stands_for(self):
        """`release\\-` is the prefix `release-` to Gradle, and so it is here: an escape taken as written would
        name a prefix no tag carries, and every check over none would pass."""
        found = GRADLE_PROPERTIES.properties("tagPrefix = release\\-\nversion = 1.0\\u002e0\nk\\ ey = a\\tb\n")
        self.assertEqual(found, {"tagPrefix": "release-", "version": "1.0.0", "k ey": "a\tb"})

    def test_a_colon_or_white_space_separates_as_the_equals_sign_does(self):
        found = GRADLE_PROPERTIES.properties("version: 1.0.0\ntagPrefix v\n")
        self.assertEqual(found, {"version": "1.0.0", "tagPrefix": "v"})

    def test_a_malformed_unicode_escape_is_refused_as_gradle_refuses_it(self):
        with self.assertRaises(SystemExit):
            GRADLE_PROPERTIES.properties("version = 1.0.\\u00\n")

    def test_a_surrogate_pair_is_one_character_and_a_lone_surrogate_is_kept(self):
        """Java reads every `\\uXXXX` as one UTF-16 unit, so two that make a surrogate pair are one character, and
        one left alone is kept as it is rather than refused."""
        text = ("tagPrefix = \\uD83D\n"
                "version = \\uD83D\\uDE00\n"
                "apart = \\uDE00\\uD83Dx\\uD83D\\uD83Dx\\uDE00\n")
        expected = {"tagPrefix": "\ud83d", "version": "\U0001F600", "apart": "\ude00\ud83dx\ud83d\ud83dx\ude00"}
        self.assertEqual(GRADLE_PROPERTIES.properties(text), expected)

    def test_comments_and_blank_lines_declare_nothing(self):
        self.assertEqual(GRADLE_PROPERTIES.properties("# version=9.9.9\n\n  \nversion = 1.0.0\n! version=8.8.8\n"),
                         {"version": "1.0.0"})


if __name__ == "__main__":
    unittest.main()
