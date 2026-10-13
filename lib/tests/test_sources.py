"""Tests for the adapters in rules/sources.py:
what every adapter has to answer, and what the Gradle one does to its file.

All of it runs over text, because the adapters are plain objects over text.
Reading and writing the file an adapter names is main.py's job, and test_main.py tests that.

Run with `python3 -m unittest discover -s lib` from the repository root.
"""

import unittest

from rules import sources

GRADLE_PROPERTIES = sources.SOURCES["gradle.properties"]

# For each source that declares a version: its file as it stands between releases, version marked.
# A new source has to add one here; test_every_declaring_source_has_a_file_to_be_tried_on fails until it does.
FILES_TO_TRY_ON = {
    "gradle.properties": "group = cz.loplex\nversion = 0.1.1-SNAPSHOT\ntagPrefix = v\n",
}


class WhatEverySourceAnswers(unittest.TestCase):
    """The contract main.py relies on, asked of every adapter in SOURCES."""

    def test_every_source_is_filed_under_the_name_it_answers_to(self):
        for name, adapter in sources.SOURCES.items():
            self.assertEqual(adapter.name, name)

    def test_a_source_declaring_nothing_names_no_file(self):
        for adapter in sources.SOURCES.values():
            if not adapter.declares_a_version:
                with self.subTest(adapter.name):
                    self.assertIsNone(adapter.file)

    def test_a_source_declaring_a_version_names_its_file_and_what_it_is_looked_in_for(self):
        """main.py reads the file, and refuses a missing one by saying what it was read for.
        An adapter without `file` or `holds` would end in a traceback on its first run instead."""
        for adapter in sources.SOURCES.values():
            if adapter.declares_a_version:
                with self.subTest(adapter.name):
                    self.assertTrue(getattr(adapter, "file", None))
                    self.assertTrue(getattr(adapter, "holds", None))

    def test_a_source_declaring_a_version_says_how_its_file_is_read_and_written(self):
        """main.py opens the file in the adapter's encoding, to read it and to write it back.

        So the name has to be a text encoding.
        open() refuses a codec that Python has but that does not turn bytes into text, such as `base64`.
        An adapter without an encoding, or with such a codec, ends in a traceback on its first run.
        One naming None is worse, because it is silent: open() then takes the locale's encoding."""
        for adapter in sources.SOURCES.values():
            if adapter.declares_a_version:
                with self.subTest(adapter.name):
                    self.assertTrue(getattr(adapter, "encoding", None))
                    "".encode(adapter.encoding)

    def test_every_declaring_source_has_a_file_to_be_tried_on(self):
        declaring = {name for name, adapter in sources.SOURCES.items() if adapter.declares_a_version}
        self.assertEqual(declaring, set(FILES_TO_TRY_ON))

    def test_what_is_written_is_what_is_read_back(self):
        """The reader and the writer of one file have to agree on how the line is written.
        Where they drift apart, the writing stops working while the reading goes on, and nothing notices."""
        for name, text in FILES_TO_TRY_ON.items():
            with self.subTest(name):
                adapter = sources.SOURCES[name]
                self.assertEqual(adapter.version(adapter.with_version(text, "0.1.1")), "0.1.1")

    def test_writing_the_version_leaves_the_prefix_as_it_was(self):
        for name, text in FILES_TO_TRY_ON.items():
            with self.subTest(name):
                adapter = sources.SOURCES[name]
                self.assertEqual(adapter.tag_prefix(adapter.with_version(text, "0.1.1")), adapter.tag_prefix(text))


class NamingASource(unittest.TestCase):
    """`--version-source` names a source, and for gradle.properties also the key its version is read under."""

    def test_a_bare_name_is_the_adapter_filed_under_it(self):
        for name, adapter in sources.SOURCES.items():
            with self.subTest(name):
                self.assertIs(sources.source(name), adapter)

    def test_a_key_after_the_name_is_where_the_version_is_read(self):
        adapter = sources.source("gradle.properties:appVersion")
        self.assertEqual(adapter.version("version = 9.9.9\nappVersion = 0.2.0-SNAPSHOT\n"), "0.2.0-SNAPSHOT")
        self.assertEqual(sources.source("gradle.properties").key, "version")

    def test_what_names_no_source_or_no_key_to_read_is_refused(self):
        """A key that would need escapes in the file is refused, not escaped: none of the keys in use needs any."""
        for spec in ("", "pom.xml", "gradle.properties:", "tags:appVersion", "gradle.properties:tagPrefix",
                     "gradle.properties:app version", "gradle.properties:app=version", "gradle.properties:a:b"):
            with self.subTest(spec), self.assertRaises(ValueError):
                sources.source(spec)


class GradlePropertiesUnderAnotherKey(unittest.TestCase):
    """A project whose build reads its version from a key of its own keeps `version` for what Gradle does with it."""

    APP_VERSION = sources.source("gradle.properties:appVersion")
    TEXT = "version = 1.0.0\nappVersion = 0.2.0-SNAPSHOT\ntagPrefix = v\n"

    def test_only_the_key_named_is_rewritten(self):
        self.assertEqual(self.APP_VERSION.with_version(self.TEXT, "0.2.0"),
                         "version = 1.0.0\nappVersion = 0.2.0\ntagPrefix = v\n")

    def test_a_key_a_continuation_splits_is_written_whole_under_its_own_name(self):
        self.assertEqual(self.APP_VERSION.with_version("\tapp\\\n  Version = 0.1.0\n", "0.2.0"),
                         "\tappVersion = 0.2.0\n")

    def test_a_file_without_the_key_is_refused_naming_it(self):
        for read in (lambda text: self.APP_VERSION.version(text),
                     lambda text: self.APP_VERSION.with_version(text, "0.2.0")):
            with self.assertRaises(SystemExit) as refused:
                read("version = 0.1.0\ntagPrefix = v\n")
            self.assertIn("appVersion", str(refused.exception))

    def test_the_prefix_is_read_from_tagPrefix_as_before(self):
        self.assertEqual(self.APP_VERSION.tag_prefix(self.TEXT), "v")


class RewritingGradleProperties(unittest.TestCase):
    """What a release does to gradle.properties: before it builds, and again once it is out.

    This is done here, not by a pattern in a workflow.
    A reader and a writer that have to agree on how the line is written can drift apart in silence:
    the reading goes on working, and only the writing stops."""

    TIGHT = "group=cz.loplex\nversion=0.1.1-SNAPSHOT\ntagPrefix=v\n"
    SPACED = "group = cz.loplex\nversion = 0.2.1-SNAPSHOT\ntagPrefix =\n"

    def test_a_tight_separator_stays_tight(self):
        self.assertIn("version=0.1.1\n", GRADLE_PROPERTIES.with_version(self.TIGHT, "0.1.1"))

    def test_a_spaced_separator_stays_spaced(self):
        self.assertIn("version = 0.2.1\n", GRADLE_PROPERTIES.with_version(self.SPACED, "0.2.1"))

    def test_nothing_but_the_version_line_moves(self):
        """Comments and blank lines included.
        A real gradle.properties has both, and a writer that dropped them would put a change nobody made into the
        release commit."""
        text = "# the build\n\n" + self.SPACED
        self.assertEqual(GRADLE_PROPERTIES.with_version(text, "0.2.1"), text.replace("0.2.1-SNAPSHOT", "0.2.1"))

    def test_a_key_that_merely_ends_in_version_is_left_alone(self):
        """`plugin.version` is spelled the way gradle.properties really spells it.
        A fixture that also differed in case, `pluginVersion`, would pass under a writer that matched only the end
        of the key, because it would not match either way.

        The key is tried alone first.
        Next to a real `version` line, a writer that took both would be refused for declaring the version twice,
        and the test would fail on that refusal instead of on the rewritten key."""
        with self.assertRaises(SystemExit):
            GRADLE_PROPERTIES.with_version("plugin.version = 9.9.9\n", "0.2.0")
        text = "plugin.version = 9.9.9\nversion = 0.1.0\n"
        written = GRADLE_PROPERTIES.with_version(text, "0.2.0")
        self.assertIn("plugin.version = 9.9.9\n", written)
        self.assertIn("version = 0.2.0\n", written)

    def test_an_indented_declaration_is_rewritten_where_it_is_read(self):
        """properties() reads past the white space before a key, as Gradle does, so both take an indented
        declaration.
        Rewritten, it keeps its indentation and its separator: changing either would be a change nobody made."""
        self.assertEqual(GRADLE_PROPERTIES.with_version("\tversion = 0.1.0\n", "0.2.0"), "\tversion = 0.2.0\n")
        self.assertEqual(GRADLE_PROPERTIES.with_version("\tversion=0.1.0\n", "0.2.0"), "\tversion=0.2.0\n")

    def test_the_version_is_written_as_data(self):
        """`&` and a backreference are characters in a version, not instructions.
        Under sed, or under a regular expression's own substitution, they would be instructions:
        that is half of why the writer is neither."""
        written = GRADLE_PROPERTIES.with_version(self.SPACED, "1.0.0-a&b\\1")
        self.assertIn("version = 1.0.0-a&b\\\\1\n", written)
        self.assertEqual(GRADLE_PROPERTIES.version(written), "1.0.0-a&b\\1")

    def test_a_crlf_line_keeps_its_carriage_return(self):
        self.assertEqual(GRADLE_PROPERTIES.with_version("a=1\r\nversion = 0.1.1-SNAPSHOT\r\nb=2\r\n", "0.1.1"),
                         "a=1\r\nversion = 0.1.1\r\nb=2\r\n")

    def test_a_file_naming_no_version_is_refused_rather_than_left_as_it_was(self):
        with self.assertRaises(SystemExit):
            GRADLE_PROPERTIES.with_version("group = cz.loplex\n", "0.2.1")

    def test_a_version_declared_twice_is_refused_rather_than_rewritten_once(self):
        """Gradle takes the last declaration.
        A writer that rewrote the first would leave the build on the version it was asked to replace."""
        with self.assertRaises(SystemExit):
            GRADLE_PROPERTIES.with_version("version = 0.1.1-SNAPSHOT\nversion = 0.1.1-SNAPSHOT\n", "0.1.1")

    def test_a_declaration_continued_onto_the_next_line_is_rewritten_whole(self):
        written = GRADLE_PROPERTIES.with_version("a=1\nversion = 0.1.\\\n  1-SNAPSHOT\nb=2\n", "0.1.1")
        self.assertEqual(written, "a=1\nversion = 0.1.1\nb=2\n")

    def test_a_colon_separator_stays_a_colon(self):
        self.assertEqual(GRADLE_PROPERTIES.with_version("version: 0.1.1-SNAPSHOT\n", "0.1.1"), "version: 0.1.1\n")

    def test_a_key_a_continuation_splits_is_written_whole(self):
        """Gradle joins `ver\\` and `sion` into one key, so the version is read there.
        The first line holds only part of the key, and putting it back would leave the file declaring `ver`."""
        written = GRADLE_PROPERTIES.with_version("\tver\\\n  sion = 0.1.0\ntagPrefix = v\n", "0.2.0")
        self.assertEqual(written, "\tversion = 0.2.0\ntagPrefix = v\n")

    def test_the_version_is_escaped_as_properties_store_escapes_a_value(self):
        """Written as data, a version still has to be read back as it was given.
        So these are escaped as Properties.store(OutputStream) escapes them:
        - a character below a space or above `~`, in Latin-1 or outside it;
        - a leading space;
        - a character the format reads as a separator or a comment."""
        given = " 1=2:3#4!5\t6\u20ac 7\x01\u00e9\U0001F600"
        written = GRADLE_PROPERTIES.with_version("version = 0.1.0\n", given)
        self.assertEqual(written, "version = \\ 1\\=2\\:3\\#4\\!5\\t6\\u20AC 7\\u0001\\u00E9\\uD83D\\uDE00\n")
        self.assertEqual(GRADLE_PROPERTIES.version(written), given)


class ReadingGradleProperties(unittest.TestCase):
    """gradle.properties is where a release reads the version it is asked to be, and the prefix its tag carries.

    Gradle accepts spaces around the `=`, and projects use both spellings.
    A reader that knew only one would report a file that declares nothing when it declares it the other way."""

    def test_a_declaration_written_tight_is_read(self):
        self.assertEqual(GRADLE_PROPERTIES.version("version=0.2.1-SNAPSHOT\n"), "0.2.1-SNAPSHOT")

    def test_a_declaration_written_with_spaces_is_read(self):
        self.assertEqual(GRADLE_PROPERTIES.version("version = 0.2.1-SNAPSHOT\n"), "0.2.1-SNAPSHOT")

    def test_a_file_naming_no_version_is_refused(self):
        with self.assertRaises(SystemExit):
            GRADLE_PROPERTIES.version("group = cz.loplex\n")

    def test_a_prefix_declared_empty_is_not_a_prefix_left_out(self):
        """A project that tags bare versions says so, with an empty prefix.
        That is not the same as a project that forgot to say anything."""
        self.assertEqual(GRADLE_PROPERTIES.tag_prefix("tagPrefix =\n"), "")
        with self.assertRaises(SystemExit):
            GRADLE_PROPERTIES.tag_prefix("version = 1.0.0\n")

    def test_a_file_that_says_nothing_about_the_prefix_is_refused(self):
        """There is no default, because a wrong guess passes.
        A repository tagging bare versions, read as tagging `v*`, has no released tags at all,
        and every check over them then passes having compared nothing."""
        with self.assertRaises(SystemExit):
            GRADLE_PROPERTIES.tag_prefix("version = 1.0.0\n")

    def test_a_line_continued_onto_the_next_is_one_declaration(self):
        """Gradle reads a line ending in a backslash as going on in the next.
        So the `version` below is part of the jvmargs value, and declares nothing.
        A reader that took it would release a version the build never sees."""
        found = GRADLE_PROPERTIES.properties("org.gradle.jvmargs=-Xmx1g \\\n    version = 0.1.0\ntagPrefix = v\n")
        self.assertEqual(found, {"org.gradle.jvmargs": "-Xmx1g version = 0.1.0", "tagPrefix": "v"})

    def test_an_even_run_of_backslashes_ends_the_line(self):
        found = GRADLE_PROPERTIES.properties("path = C:\\\\dir\\\\\nversion = 1.0.0\n")
        self.assertEqual(found, {"path": "C:\\dir\\", "version": "1.0.0"})

    def test_an_escape_is_read_as_what_it_stands_for(self):
        """`release\\-` is the prefix `release-` to Gradle, and so it is here.
        An escape taken as written would name a prefix no tag carries, and every check, finding no release,
        would pass."""
        found = GRADLE_PROPERTIES.properties("tagPrefix = release\\-\nversion = 1.0\\u002e0\nk\\ ey = a\\tb\n")
        self.assertEqual(found, {"tagPrefix": "release-", "version": "1.0.0", "k ey": "a\tb"})

    def test_a_colon_or_white_space_separates_as_the_equals_sign_does(self):
        found = GRADLE_PROPERTIES.properties("version: 1.0.0\ntagPrefix v\n")
        self.assertEqual(found, {"version": "1.0.0", "tagPrefix": "v"})

    def test_a_malformed_unicode_escape_is_refused_as_gradle_refuses_it(self):
        with self.assertRaises(SystemExit):
            GRADLE_PROPERTIES.properties("version = 1.0.\\u00\n")

    def test_a_surrogate_pair_is_one_character_and_a_lone_surrogate_is_kept(self):
        """Java reads every `\\uXXXX` as one UTF-16 unit.
        So two that make a surrogate pair are one character, and one alone is kept as it is, not refused."""
        text = ("tagPrefix = \\uD83D\n"
                "version = \\uD83D\\uDE00\n"
                "apart = \\uDE00\\uD83Dx\\uD83D\\uD83Dx\\uDE00\n")
        expected = {"tagPrefix": "\ud83d", "version": "\U0001F600", "apart": "\ude00\ud83dx\ud83d\ud83dx\ude00"}
        self.assertEqual(GRADLE_PROPERTIES.properties(text), expected)

    def test_comments_and_blank_lines_declare_nothing(self):
        self.assertEqual(GRADLE_PROPERTIES.properties("# version=9.9.9\n\n  \nversion = 1.0.0\n! version=8.8.8\n"),
                         {"version": "1.0.0"})
