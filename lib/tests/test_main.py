"""Tests for main.py, the command line: its subcommands over repositories built for the purpose,
and the arguments it refuses.

Run with `python3 -m unittest discover -s lib` from the repository root.
"""

import argparse
import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

import main
from rules.steps import Asked, MAJOR, MINOR, next_candidate
from rules import repository
from rules.repository import released_versions

from .fixtures import TwoReleasesOneOffMain

SCRIPT = Path(__file__).resolve().parent.parent / "main.py"

version_command = main.version_command
prefix_from = main.prefix_from


class TheReleaseNotes(unittest.TestCase):
    """One released section's text, printed for the release page.
    It comes from the file the changelog check holds to the tag, so the two cannot say different things.
    The one exception is the warning release-flow/warn puts above the notes while publishing elsewhere has not
    completed."""

    def notes_of(self, changelog, version):
        here = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (here / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
        original = repository.REPO
        repository.REPO = here
        self.addCleanup(setattr, repository, "REPO", original)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            problems = main.notes_command(argparse.Namespace(version=version))
        return out.getvalue(), problems

    TEXT = ("# Log\n\n## [Unreleased]\n\n## [0.2.0] - 2026-09-21\n\n### Added\n\n- A\n\n"
            "## [0.1.0] - 2026-09-01\n\n- old\n\n[0.2.0]: https://example.invalid/x\n")

    def test_the_notes_are_the_section_without_its_heading(self):
        """No `## [0.2.0] - date` line: the release page has a title of its own, and the date would read as
        the first entry."""
        notes, problems = self.notes_of(self.TEXT, "0.2.0")
        self.assertEqual(problems, [])
        self.assertEqual(notes, "### Added\n\n- A\n")

    def test_link_definitions_are_not_notes(self):
        """Asked of the last section, because the definitions at the foot fall into its body.
        Any other section ends at the heading below it, so the definitions are outside it however it is read."""
        notes, _ = self.notes_of(self.TEXT, "0.1.0")
        self.assertNotIn("example.invalid", notes)

    def test_a_version_with_nothing_to_say_is_refused(self):
        _, problems = self.notes_of(self.TEXT.replace("### Added\n\n- A\n\n", ""), "0.2.0")
        self.assertTrue(problems)
        self.assertIn("holds nothing for 0.2.0", problems[0])

    def test_a_section_holding_only_spaces_is_refused_too(self):
        """Blank lines are taken off a body's ends, but spaces are not; a line of spaces is still nothing to say."""
        _, problems = self.notes_of(self.TEXT.replace("### Added\n\n- A\n", "   \n"), "0.2.0")
        self.assertTrue(problems)
        self.assertIn("holds nothing for 0.2.0", problems[0])

    def test_a_version_with_no_section_is_refused(self):
        _, problems = self.notes_of(self.TEXT, "0.3.0")
        self.assertTrue(problems)
        self.assertIn("holds nothing for 0.3.0", problems[0])


class TheChangelogCommand(TwoReleasesOneOffMain):
    """What `changelog` reports for a tag it cannot compare: one off this history, one that holds no text of
    its section, and one whose copy holds a line it does not read."""

    def test_a_section_off_this_history_is_not_called_deleted(self):
        with contextlib.redirect_stdout(io.StringIO()):
            problems = main.changelog_command(argparse.Namespace(version_source="tags", tag_prefix="v",
                                                                   skip_unreadable_releases=False))
        self.assertEqual(len(problems), 1)
        self.assertIn("not on this history", problems[0])

    def test_a_tag_older_than_its_section_is_reported_as_not_compared(self):
        """The report has to be honest about a section it could not compare.
        One whose tag holds no text of it is named as not compared, not counted among the sections that still
        read as released."""
        self.git("tag", "-d", "v0.2.0")
        self.git("tag", "v0.0.1")
        self.commit("## [0.1.0] - 2026-01-01\n\n- A\n\n## [0.0.1] - 2025-12-01\n\n- Z\n")
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            problems = main.changelog_command(argparse.Namespace(version_source="tags", tag_prefix="v",
                                                                   skip_unreadable_releases=False))
        self.assertEqual(problems, [])
        self.assertIn("Compared 1 released section(s)", printed.getvalue())
        self.assertIn("Not compared: 0.0.1 ", printed.getvalue())

    def test_a_tag_older_than_the_file_is_reported_as_not_compared(self):
        """A tag made before CHANGELOG.md existed has no text to compare against either.
        It is named the same way, not left out of the report."""
        self.git("tag", "-d", "v0.2.0")
        self.git("rm", "-q", "CHANGELOG.md")
        self.git("commit", "-q", "-m", "no changelog")
        self.git("tag", "v0.0.1")
        self.commit("## [0.1.0] - 2026-01-01\n\n- A\n\n## [0.0.1] - 2025-12-01\n\n- Z\n")
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            problems = main.changelog_command(argparse.Namespace(version_source="tags", tag_prefix="v",
                                                                   skip_unreadable_releases=False))
        self.assertEqual(problems, [])
        self.assertIn("Compared 1 released section(s)", printed.getvalue())
        self.assertIn("Not compared: 0.0.1 ", printed.getvalue())

    def run_changelog(self, skip_unreadable_releases: bool) -> tuple[list[str], str]:
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            problems = main.changelog_command(argparse.Namespace(version_source="tags", tag_prefix="v",
                                                                 skip_unreadable_releases=skip_unreadable_releases))
        return problems, printed.getvalue()

    def test_a_line_below_the_tagged_section_is_not_read(self):
        """The copy at v0.1.0 is read down to the end of [0.1.0]: a block quote in an older section does not matter."""
        self.git("tag", "-d", "v0.1.0", "v0.2.0")
        self.commit("## [0.1.0] - 2026-01-01\n\n- A\n\n## [0.0.9] - 2025-01-01\n\n> quoted\n")
        self.git("tag", "v0.1.0")
        self.commit("## [0.1.0] - 2026-01-01\n\n- A\n\n## [0.0.9] - 2025-01-01\n\n- quoted\n")
        problems, printed = self.run_changelog(skip_unreadable_releases=False)
        self.assertEqual(problems, [])
        self.assertIn("Compared 1 released section(s)", printed)

    def test_a_line_not_read_in_the_tagged_section_fails_unless_skipped(self):
        """A tag cannot be edited, so the refusal stands for good; --skip-unreadable-releases names the release as not
        compared instead."""
        self.git("tag", "-d", "v0.1.0", "v0.2.0")
        self.commit("## [0.1.0] - 2026-01-01\n\n> A\n")
        self.git("tag", "v0.1.0")
        self.commit("## [0.1.0] - 2026-01-01\n\n- A\n")
        problems, _ = self.run_changelog(skip_unreadable_releases=False)
        self.assertEqual(len(problems), 1)
        for said in ("line 5 holds a block quote", "as tagged v0.1.0", "[0.1.0] cannot be compared",
                     "--skip-unreadable-releases"):
            self.assertIn(said, problems[0])
        self.assertNotIn(": write", problems[0])  # The tag cannot be edited.
        problems, printed = self.run_changelog(skip_unreadable_releases=True)
        self.assertEqual(problems, [])
        self.assertIn("Compared 0 released section(s)", printed)
        self.assertIn("Not compared: 0.1.0 - CHANGELOG.md line 5 holds a block quote", printed)
        self.assertNotIn(": write", printed)

    def test_a_skipped_tag_read_into_its_section_still_needs_it_in_the_tree(self):
        """The copy at v0.1.0 is read past `## [0.1.0]` before the line it refuses, so the tag holds that section.
        Skipped or not, a tree without it has lost it."""
        self.git("tag", "-d", "v0.1.0", "v0.2.0")
        self.commit("## [0.1.0] - 2026-01-01\n\n> A\n")
        self.git("tag", "v0.1.0")
        self.commit("## [0.2.0] - 2026-02-01\n\n- B\n")
        problems, printed = self.run_changelog(skip_unreadable_releases=True)
        self.assertEqual(problems, ["[0.1.0] is released but its section is gone"])
        self.assertNotIn("Not compared: 0.1.0", printed)
        problems, _ = self.run_changelog(skip_unreadable_releases=False)
        self.assertTrue(problems[0].endswith("names it as not compared instead, but its section is not in this tree, "
                                             "which fails either way"), problems[0])

    def test_a_skipped_tag_refused_above_its_section_is_not_called_deleted(self):
        """Refused above `## [0.1.0]`, the copy may be older than that section, so a tree without it proves nothing.
        The release is named as not compared, with what is not known."""
        self.git("tag", "-d", "v0.1.0", "v0.2.0")
        self.commit("> intro\n\n## [0.1.0] - 2026-01-01\n\n- A\n")
        self.git("tag", "v0.1.0")
        self.commit("## [0.2.0] - 2026-02-01\n\n- B\n")
        problems, printed = self.run_changelog(skip_unreadable_releases=True)
        self.assertEqual(problems, [])
        self.assertIn("Not compared: 0.1.0 - CHANGELOG.md line 3 holds a block quote", printed)
        self.assertIn("the tree has no section for it, and the tag may never have had one", printed)

    def test_a_skipped_tag_is_named_even_when_the_check_fails(self):
        self.git("tag", "-d", "v0.1.0", "v0.2.0")
        self.commit("## [0.1.0] - 2026-01-01\n\n> A\n")
        self.git("tag", "v0.1.0")
        self.commit("## [0.2.0] - 2026-02-01\n\n- B\n\n## [0.1.0] - 2026-01-01\n\n- A\n")
        self.git("tag", "v0.2.0")
        self.commit("## [0.2.0] - 2026-02-01\n\n- B, reworded\n\n## [0.1.0] - 2026-01-01\n\n- A\n")
        problems, printed = self.run_changelog(skip_unreadable_releases=True)
        self.assertEqual(problems, ["[0.2.0] is released but its section no longer reads as the tag has it"])
        self.assertIn("Not compared: 0.1.0 - CHANGELOG.md line 5 holds a block quote", printed)


class WritingTheVersionBack(unittest.TestCase):
    """`set-version` against a file on disk, where the line endings and the read-back matter."""

    def properties_file_holding(self, text: str) -> Path:
        here = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        (here / "gradle.properties").write_bytes(text.encode("utf-8"))
        original = repository.REPO
        repository.REPO = here
        self.addCleanup(setattr, repository, "REPO", original)
        return here / "gradle.properties"

    def set_version(self, version: str) -> list[str]:
        with contextlib.redirect_stdout(io.StringIO()):
            return main.set_version_command(
                argparse.Namespace(version=version, version_source="gradle.properties", tag_prefix=None))

    def test_a_crlf_file_stays_crlf(self):
        """Read the way open() reads by default, every line would come back as LF.
        The release commit would then rewrite the whole file to change one line."""
        path = self.properties_file_holding("group=a\r\nversion=0.1.1-SNAPSHOT\r\ntagPrefix=v\r\n")
        self.assertEqual(self.set_version("0.1.1"), [])
        self.assertEqual(path.read_bytes(), b"group=a\r\nversion=0.1.1\r\ntagPrefix=v\r\n")

    def test_a_rewrite_that_did_not_take_is_caught_on_reading_back(self):
        """The read-back catches a writer and a reader that have come to disagree, which would otherwise fail
        silently.
        A writer that changes nothing stands in for that here."""
        self.properties_file_holding("version = 0.1.1-SNAPSHOT\n")
        with unittest.mock.patch.object(main.SOURCES["gradle.properties"], "with_version",
                                        lambda text, version: text):
            problems = self.set_version("0.1.1")
        self.assertTrue(problems)
        self.assertIn("still does not name 0.1.1", problems[0])

    def test_a_write_that_did_not_reach_the_file_is_caught_on_reading_back(self):
        """The other case the read-back is for: a rewrite that is right in memory but never reaches the file.
        A check over the rewritten text would pass it."""
        self.properties_file_holding("version = 0.1.1-SNAPSHOT\n")
        real_open = open

        def dropping_writes(file, mode="r", *arguments, **keywords):
            return io.StringIO() if "w" in mode else real_open(file, mode, *arguments, **keywords)

        with unittest.mock.patch.object(main, "open", dropping_writes, create=True):
            problems = self.set_version("0.1.1")
        self.assertTrue(problems)
        self.assertIn("still does not name 0.1.1", problems[0])

    def test_a_version_outside_latin_1_is_written_escaped_rather_than_breaking_the_file(self):
        """A character with no byte in the file's encoding would stop the write halfway, with the file already
        emptied.
        It is escaped instead, as Properties.store(OutputStream) escapes it, and reads back as it was given."""
        path = self.properties_file_holding("version = 0.1.1-SNAPSHOT\n")
        self.assertEqual(self.set_version("0.1.1-\u20ac"), [])
        self.assertEqual(path.read_bytes(), b"version = 0.1.1-\\u20AC\n")

    def test_a_lone_surrogate_in_the_version_leaves_the_file_as_it_was(self):
        """A lone surrogate handed to set_version_command directly is refused by stored().
        That happens before the file is opened for writing, so the file is left as it was, not emptied.
        From the command line, main() refuses it before it gets this far."""
        path = self.properties_file_holding("version = 0.1.1-SNAPSHOT\n")
        with self.assertRaises(UnicodeEncodeError):
            self.set_version("0.1.1-\udcff")
        self.assertEqual(path.read_bytes(), b"version = 0.1.1-SNAPSHOT\n")

    def test_a_comment_or_a_value_in_any_encoding_comes_back_in_its_own_bytes(self):
        """Gradle reads gradle.properties one byte to one character.
        So a comment in UTF-8, one in Latin-1, one holding every byte above ASCII, and a value in UTF-8
        are all as good as ASCII to it.
        A release leaves each of them exactly as it was."""
        path = self.properties_file_holding("")
        path.write_bytes("# sestaven\u00ed\n".encode("utf-8") + "# sestaven\u00ed\n".encode("iso-8859-1")
                         + b"# " + bytes(range(0x80, 0x100)) + b"\ndescription = " + "sestaven\u00ed".encode("utf-8")
                         + b"\nversion = 0.1.1-SNAPSHOT\n")
        before = path.read_bytes()
        self.assertEqual(self.set_version("0.1.1"), [])
        self.assertEqual(path.read_bytes(), before.replace(b"0.1.1-SNAPSHOT", b"0.1.1"))


class ReadingTheFile(unittest.TestCase):
    """The file a source names, read from disk in the encoding its format is read in."""

    def test_gradle_properties_is_read_a_byte_to_a_character_as_gradle_reads_it(self):
        """Gradle reads each byte of the file as the character with that code.
        So no byte above ASCII is decoded as UTF-8 or through another single-byte table.
        The prefix a release uses has to be the one the build sees."""
        here = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        (here / "gradle.properties").write_bytes(b"version = 0.1.1-SNAPSHOT\ntagPrefix = " + bytes(range(0x80, 0x100))
                                                 + b"\n")
        original = repository.REPO
        repository.REPO = here
        self.addCleanup(setattr, repository, "REPO", original)
        self.assertEqual(main.prefix_from("gradle.properties", None), "".join(map(chr, range(0x80, 0x100))))


class WritingTheChangelogBack(unittest.TestCase):
    """`close-changelog` against a file; closed() itself is exercised over text in test_changelog.py."""

    def changelog_file_holding(self, text: str) -> Path:
        here = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        (here / "CHANGELOG.md").write_bytes(text.encode("utf-8"))
        original = repository.REPO
        repository.REPO = here
        self.addCleanup(setattr, repository, "REPO", original)
        return here / "CHANGELOG.md"

    def test_a_crlf_file_stays_crlf(self):
        """A CRLF file stays CRLF, for the same reason as in set-version:
        a release commit should change one section of the file, not every line of it."""
        path = self.changelog_file_holding("# Log\r\n\r\n## [Unreleased]\r\n\r\n### Added\r\n\r\n- A\r\n")
        with contextlib.redirect_stdout(io.StringIO()):
            problems = main.close_changelog_command(argparse.Namespace(
                version="0.1.0", date="2026-09-21", repository_url=None, version_source="tags", tag_prefix="v"))
        self.assertEqual(problems, [])
        self.assertEqual(path.read_bytes(),
                         b"# Log\r\n\r\n## [Unreleased]\r\n\r\n## [0.1.0] - 2026-09-21\r\n\r\n### Added\r\n\r\n- A\r\n")

    def test_a_file_of_lone_crs_stays_so(self):
        """A lone CR ends a line, as open() reads one by default, and the file keeps its lone CRs instead of coming
        back as LF."""
        path = self.changelog_file_holding("# Log\r\r## [Unreleased]\r\r### Added\r\r- A\r")
        with contextlib.redirect_stdout(io.StringIO()):
            problems = main.close_changelog_command(argparse.Namespace(
                version="0.1.0", date="2026-09-21", repository_url=None, version_source="tags", tag_prefix="v"))
        self.assertEqual(problems, [])
        self.assertEqual(path.read_bytes(),
                         b"# Log\r\r## [Unreleased]\r\r## [0.1.0] - 2026-09-21\r\r### Added\r\r- A\r")

    def test_a_refused_close_leaves_the_file_as_it_was(self):
        """A refusal is the rules saying no, and the changelog is still the one to fix, so it is left as it was."""
        text = "# Log\n\n## [Unreleased]\n\n## [0.1.0] - 2026-09-01\n\n- A\n"
        path = self.changelog_file_holding(text)
        with self.assertRaises(SystemExit):
            main.close_changelog_command(argparse.Namespace(
                version="0.2.0", date="2026-09-21", repository_url=None, version_source="tags", tag_prefix="v"))
        self.assertEqual(path.read_bytes(), text.encode("utf-8"))


class AChangelogWithALineNotRead(unittest.TestCase):
    """Every command that reads CHANGELOG.md refuses one with a line outside the part of Markdown read here,
    by its number (see rules/markdown.py)."""

    def test_every_command_that_reads_the_changelog_refuses_it(self):
        here = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        (here / "CHANGELOG.md").write_text("# Log\n\n## [Unreleased]\n\n- A\n\n> ## [0.1.0] - x\n",
                                           encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=here, check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                        "commit", "-q", "--allow-empty", "-m", "init"], cwd=here, check=True)
        original = repository.REPO
        repository.REPO = here
        self.addCleanup(setattr, repository, "REPO", original)
        for command, arguments in ((main.version_command, dict(version="0.1.0")),
                                   (main.changelog_command, {}),
                                   (main.close_changelog_command,
                                    dict(version="0.1.0", date="2026-09-21", repository_url=None)),
                                   (main.notes_command, dict(version="0.1.0"))):
            with self.subTest(command.__name__):
                with (contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()),
                      self.assertRaises(SystemExit) as raised):
                    command(argparse.Namespace(version_source="tags", tag_prefix="v", skip_unreadable_releases=False,
                                               **arguments))
                self.assertIn("line 7 holds a block quote", str(raised.exception))


class AVersionHandedIn(unittest.TestCase):
    """`--version` given in place of what the file declares, with or without the marker.
    Only a marker at the end of the version is taken off.
    A version carrying it anywhere else is still one being worked on."""

    def released_as(self, given):
        here = Path(self.enterContext(tempfile.TemporaryDirectory()))
        subprocess.run(["git", "init", "-q"], cwd=here, check=True)
        (here / "gradle.properties").write_text("version = 0.9.9-SNAPSHOT\ntagPrefix = v\n", encoding="utf-8")
        (here / "CHANGELOG.md").write_text("# Changelog\n\n## [Unreleased]\n", encoding="utf-8")
        original = repository.REPO
        repository.REPO = here
        self.addCleanup(setattr, repository, "REPO", original)
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            problems = version_command(argparse.Namespace(version=given,
                                                          version_source="gradle.properties", tag_prefix="v"))
        return problems, printed.getvalue().strip()

    def test_a_version_handed_in_without_the_marker_is_released_as_it_is(self):
        self.assertEqual(self.released_as("0.2.0"), ([], "0.2.0"))

    def test_a_version_handed_in_with_the_marker_is_released_without_it(self):
        self.assertEqual(self.released_as("0.2.0-SNAPSHOT"), ([], "0.2.0"))

    def test_a_marker_that_does_not_end_the_version_is_not_taken_off(self):
        """`1.0.0-SNAPSHOT+b` is refused as what it is, a version being worked on."""
        problems, printed = self.released_as("1.0.0-SNAPSHOT+b")
        self.assertEqual((len(problems), printed), (1, ""))
        self.assertIn("1.0.0-SNAPSHOT+b is a version being worked on", problems[0])


class TheSourceAVersionComesFrom(unittest.TestCase):
    """The one thing a project type decides, which is two separate questions:
    - where the version is read from;
    - whether anything is written once it is released.
    A repository whose version lives only in its tags answers the first with "you tell me, or the one after
    the highest release, or a later one [Unreleased] asks for".
    It answers the second with "nowhere".
    The tests of the default version call next_candidate over released_versions(): the default `version` computes
    over the repository's real tags, so they hold rules/steps.py and rules/repository.py together."""

    def repository_with(self, *tags, declaring=None, changelog="# Changelog\n\n## [Unreleased]\n"):
        here = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        if changelog is not None:
            (here / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=here, check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                        "commit", "-q", "--allow-empty", "-m", "init"], cwd=here, check=True)
        for tag in tags:
            subprocess.run(["git", "tag", tag], cwd=here, check=True)
        if declaring is not None:
            (here / "gradle.properties").write_text(declaring, encoding="utf-8")
        original = repository.REPO
        repository.REPO = here
        self.addCleanup(setattr, repository, "REPO", original)
        return here

    def problems_releasing(self, given, *tags, version_source="tags", prefix="v", **repository):
        # The command prints the version it accepted.
        # It is swallowed here, so that the suite's output holds only test results.
        self.repository_with(*tags, **repository)
        with contextlib.redirect_stdout(io.StringIO()):
            return version_command(argparse.Namespace(version=given, version_source=version_source, tag_prefix=prefix))

    def test_a_tag_source_releases_the_version_it_is_handed(self):
        self.repository_with("v0.1.0")
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            problems = version_command(argparse.Namespace(version="0.2.0", version_source="tags", tag_prefix="v"))
        self.assertEqual((problems, printed.getvalue().strip()), ([], "0.2.0"))

    def test_the_default_is_the_patch_after_the_highest_release(self):
        """A dispatch leaves the version field empty, rather than computing a default in its form.
        With nothing under [Unreleased] asking for more, the patch after the highest release comes back.
        Which release is the highest when their names sort differently is the next test's question."""
        self.repository_with("v0.1.0", "v0.2.0")
        self.assertEqual(next_candidate(released_versions("v")), "0.2.1")

    def test_the_default_is_measured_by_precedence_not_by_how_tags_sort(self):
        """`git tag -l` lists tags in ASCII order, where `v0.10.0` sorts before `v0.9.0`.
        Taking the last one listed would offer `0.9.1` as the version after `0.10.0`.
        The step check would then refuse a default next_candidate produced."""
        self.repository_with("v0.9.0", "v0.10.0")
        self.assertEqual(next_candidate(released_versions("v")), "0.10.1")

    def test_an_open_train_is_defaulted_to_the_release_it_was_for(self):
        self.repository_with("v0.1.0", "v0.2.0-rc.1")
        self.assertEqual(next_candidate(released_versions("v")), "0.2.0")

    def test_the_default_moves_as_far_as_unreleased_asks(self):
        """Left empty, the version is the least one that what waits to be released allows:
        the minor after an addition, and from 1.0 on the major after a removal.
        That holds even where an open train would be followed by less."""
        self.repository_with("v0.2.0")
        releases = released_versions("v")
        self.assertEqual(next_candidate(releases, Asked(MINOR, "### Added", [], [])), "0.3.0")
        self.assertEqual(next_candidate(releases, Asked(MAJOR, "### Removed", [], [])), "0.3.0")
        self.repository_with("v1.2.0", "v1.3.0-beta.1")
        releases = released_versions("v")
        self.assertEqual(next_candidate(releases, Asked(MINOR, "### Added", [], [])), "1.3.0")
        self.assertEqual(next_candidate(releases, Asked(MAJOR, "### Removed", [], [])), "2.0.0")

    def test_version_reads_what_unreleased_asks(self):
        """End to end: the default a dispatch leaves empty, a version handed in, and a declared one."""
        added = "# Changelog\n\n## [Unreleased]\n\n### Added\n\n- A\n"
        self.repository_with("v0.2.0", changelog=added)
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            problems = version_command(argparse.Namespace(version=None, version_source="tags", tag_prefix="v"))
        self.assertEqual((problems, printed.getvalue().strip()), ([], "0.3.0"))
        self.assertIn("at least a minor, 0.3.0", " ".join(self.problems_releasing("0.2.1", "v0.2.0", changelog=added)))
        self.repository_with("v0.2.0", declaring="version = 0.2.1-SNAPSHOT\ntagPrefix = v\n", changelog=added)
        with contextlib.redirect_stdout(io.StringIO()):
            problems = version_command(argparse.Namespace(version=None,
                                                          version_source="gradle.properties", tag_prefix=None))
        self.assertIn("[Unreleased] holds ### Added", " ".join(problems))

    def test_a_hotfix_from_a_branch_carrying_an_open_train_is_held_to_it(self):
        """0.2.1 may go out while 0.3.0-beta.1 is open, from a branch the train has not reached.
        Cut from a branch whose changelog holds the beta's section, it would release the beta's addition as a
        patch."""
        on_the_train = ("# Changelog\n\n## [Unreleased]\n\n### Fixed\n\n- F\n\n## [0.3.0-beta.1] - 2026-09-20\n\n"
                        "### Added\n\n- A\n\n## [0.2.0] - 2026-09-01\n\n- old\n")
        self.assertEqual(self.problems_releasing("0.2.1", "v0.2.0", "v0.3.0-beta.1", changelog=on_the_train),
                         ["[0.3.0-beta.1] holds ### Added, so the release after 0.2.0 is at least a minor, 0.3.0, "
                          "and 0.2.1 is not"])
        self.assertEqual(self.problems_releasing("0.3.0", "v0.2.0", "v0.3.0-beta.1", changelog=on_the_train), [])
        off_the_train = "# Changelog\n\n## [Unreleased]\n\n### Fixed\n\n- F\n\n## [0.2.0] - 2026-09-01\n\n- old\n"
        self.assertEqual(self.problems_releasing("0.2.1", "v0.2.0", "v0.3.0-beta.1", changelog=off_the_train), [])

    def test_an_entry_under_no_group_is_refused_by_name(self):
        loose = "# Changelog\n\n## [Unreleased]\n\n- loose\n\n### Fixed\n\n- F\n"
        problems = self.problems_releasing("0.2.1", "v0.2.0", changelog=loose)
        self.assertEqual(problems, ["[Unreleased] has an entry under no ### group, so nothing says what kind of "
                                    "change it is: - loose"])

    def test_a_group_of_another_name_is_noted_and_passes(self):
        self.repository_with("v0.2.0", changelog="# Changelog\n\n## [Unreleased]\n\n### Documentation\n\n- D\n")
        said = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(said):
            problems = version_command(argparse.Namespace(version="0.2.1", version_source="tags", tag_prefix="v"))
        self.assertEqual(problems, [])
        self.assertIn("'### Documentation', which is not a kind of change Keep a Changelog names", said.getvalue())

    def test_a_changelog_without_an_unreleased_section_is_told_so(self):
        """`## Unreleased` without brackets is not the section Keep a Changelog writes, and what is under it is
        not read.
        That is said on stderr, not passed silently as a patch."""
        self.repository_with("v0.2.0", changelog="# Changelog\n\n## Unreleased\n\n### Added\n\n- A\n")
        said = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(said):
            problems = version_command(argparse.Namespace(version="0.2.1", version_source="tags", tag_prefix="v"))
        self.assertEqual(problems, [])
        self.assertIn("CHANGELOG.md has no [Unreleased] section", said.getvalue())

    def test_a_repository_without_a_changelog_is_told_so_and_asked_for_a_patch(self):
        self.repository_with("v0.2.0", changelog=None)
        said = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(said):
            problems = version_command(argparse.Namespace(version="0.2.1", version_source="tags", tag_prefix="v"))
        self.assertEqual(problems, [])
        self.assertIn("there is no CHANGELOG.md here", said.getvalue())

    def test_with_nothing_released_the_first_version_is_asked_for_rather_than_guessed(self):
        self.repository_with()
        with self.assertRaises(SystemExit) as raised:
            next_candidate(released_versions("v"))
        self.assertIn("say which version to release", str(raised.exception))

    def test_tags_that_are_no_release_are_noted_once(self):
        """version_command reads the tags once and hands them to next_candidate.
        So the note that none of them is a release is said once before the refusal, not once by each."""
        self.repository_with("deploy-1")
        said = io.StringIO()
        with contextlib.redirect_stderr(said), self.assertRaises(SystemExit) as raised:
            version_command(argparse.Namespace(version=None, version_source="tags", tag_prefix="v"))
        self.assertIn("say which version to release", str(raised.exception))
        self.assertEqual(said.getvalue().count("none of them is a release"), 1, said.getvalue())

    def test_a_tag_source_still_answers_to_the_rules(self):
        """The source decides where the candidate comes from, and nothing else.
        What may follow what is the same rule for every source."""
        problems = self.problems_releasing("0.4.0", "v0.1.0")
        self.assertTrue(problems)
        self.assertIn("does not follow 0.1.0", problems[0])

    def test_a_declaring_source_with_no_marker_releases_the_version_as_declared(self):
        """`marker_of` allows a source that declares a version without a marker.
        With an empty marker, the declared version has to come out whole, not as the empty string a slice to
        `-0` leaves.
        It has to be accepted, not refused as a version nobody would release."""
        self.repository_with("v0.1.0", declaring="version = 0.2.0\n")
        printed = io.StringIO()
        with unittest.mock.patch.object(main, "marker_of", lambda source: ""), \
                contextlib.redirect_stdout(printed):
            problems = version_command(argparse.Namespace(version=None,
                                                          version_source="gradle.properties", tag_prefix="v"))
        self.assertEqual(problems, [])
        self.assertEqual(printed.getvalue().strip(), "0.2.0")

    def test_the_commit_a_release_tags_passes_as_that_release(self):
        """Publishing a release creates its tag, and a workflow on push runs for that tag.
        The source there still names the version just released, and `version` is not being asked to release it
        again."""
        self.repository_with("v0.1.0", "v0.2.0", declaring="version = 0.2.0\ntagPrefix = v\n")
        printed, said = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(printed), contextlib.redirect_stderr(said):
            problems = version_command(argparse.Namespace(version=None,
                                                          version_source="gradle.properties", tag_prefix=None))
        self.assertEqual((problems, printed.getvalue().strip()), ([], "0.2.0"))
        self.assertIn("this commit is the release of 0.2.0", said.getvalue())

    def test_a_released_version_is_refused_on_a_commit_its_tag_is_not_on(self):
        here = self.repository_with("v0.2.0", declaring="version = 0.2.0\ntagPrefix = v\n")
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                        "commit", "-q", "--allow-empty", "-m", "after"], cwd=here, check=True)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            problems = version_command(argparse.Namespace(version=None,
                                                          version_source="gradle.properties", tag_prefix=None))
        self.assertTrue(problems)
        self.assertIn("released already", " ".join(problems))

    def test_a_released_version_handed_in_on_its_tagged_commit_is_still_refused(self):
        """A version given outright is a release being asked for, wherever it is asked."""
        self.repository_with("v0.2.0", declaring="version = 0.2.0\ntagPrefix = v\n")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            problems = version_command(argparse.Namespace(version="0.2.0",
                                                          version_source="gradle.properties", tag_prefix=None))
        self.assertIn("released already", " ".join(problems))

    def test_a_tag_source_declares_no_version_to_write(self):
        """`set-version` reporting success after writing nothing is the failure worth refusing:
        a release would carry on believing it had recorded a version.
        It is refused with a status of its own, so that a caller can tell it from a write that failed."""
        self.repository_with("v0.1.0")
        said = io.StringIO()
        with contextlib.redirect_stderr(said), self.assertRaises(SystemExit) as raised:
            main.set_version_command(argparse.Namespace(version="0.2.0",
                                                                 version_source="tags", tag_prefix="v"))
        self.assertEqual(raised.exception.code, main.NOTHING_TO_WRITE)
        self.assertNotIn(main.NOTHING_TO_WRITE, (1, 2), "the status of every other refusal, and argparse's")
        self.assertIn("declares no version", said.getvalue())

    def test_a_tag_source_declares_no_prefix_either(self):
        self.repository_with("v0.1.0")
        with self.assertRaises(SystemExit) as raised:
            prefix_from("tags", None)
        self.assertIn("--tag-prefix", str(raised.exception))

    def test_a_prefix_given_outright_is_taken_over_any_the_source_declares(self):
        self.repository_with(declaring="version = 1.0.0-SNAPSHOT\ntagPrefix = v\n")
        self.assertEqual(prefix_from("gradle.properties", ""), "")
        self.assertEqual(prefix_from("gradle.properties", "release-"), "release-")
        self.assertEqual(prefix_from("gradle.properties", None), "v")

    def test_none_with_a_caret_is_no_prefix(self):
        """`^none` is how the actions say "no prefix", and they pass it on as given."""
        self.repository_with(declaring="version = 1.0.0-SNAPSHOT\ntagPrefix = v\n")
        self.assertEqual(prefix_from("gradle.properties", "^none"), "")
        self.assertEqual(prefix_from("tags", "^none"), "")

    def test_a_declared_prefix_holding_a_lone_surrogate_is_refused(self):
        """The reader keeps an unpaired `\\uD83D`, as Java keeps it.
        Taken as a prefix, it made `prefix` end in a traceback while printing it.
        A pair is one character, and is accepted."""
        self.repository_with(declaring="version = 1.0.0-SNAPSHOT\ntagPrefix = \\uD83D\n")
        with self.assertRaises(SystemExit) as raised:
            prefix_from("gradle.properties", None)
        self.assertIn("tagPrefix in gradle.properties is '\\ud83d'", str(raised.exception))
        self.repository_with(declaring="version = 1.0.0-SNAPSHOT\ntagPrefix = \\uD83D\\uDE00\n")
        self.assertEqual(prefix_from("gradle.properties", None), "\U0001F600")


class ArgumentsThatAreNotText(unittest.TestCase):
    """A command-line byte that does not decode arrives as a lone surrogate (PEP 383).
    Nothing can print or write one.
    The tests run the script for real, with the bytes on the command line, because that is the only way one
    arrives."""

    def run_with(self, *arguments):
        here = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        subprocess.run(["git", "init", "-q"], cwd=here, check=True)
        files = {"gradle.properties": b"version = 0.1.1-SNAPSHOT\ntagPrefix = v\n",
                 "CHANGELOG.md": b"# Log\n\n## [Unreleased]\n\n- B\n\n## [0.1.0] - 2026-09-01\n\n- A\n"}
        for name, content in files.items():
            (here / name).write_bytes(content)
        done = subprocess.run([sys.executable, str(SCRIPT), *arguments], cwd=here, capture_output=True, text=True)
        self.assertEqual({name: (here / name).read_bytes() for name in files}, files, "a file was written")
        return done

    def test_each_is_refused_by_name_before_anything_is_written(self):
        """set-version used to end in a traceback, and close-changelog in one with CHANGELOG.md already emptied."""
        for arguments, named_in in (
                (["set-version", b"0.1.1-\xff"], "the version argument is '0.1.1-\\udcff'"),
                (["close-changelog", b"0.1.1-\xff"], "the version argument"),
                (["close-changelog", "--date", b"2026-09-\xff", "0.1.1"], "the date argument"),
                (["close-changelog", "--repository-url", b"https://example.com/\xff", "0.1.1"],
                 "the repository-url argument"),
                (["prefix", "--tag-prefix", b"\xff"], "the tag-prefix argument")):
            with self.subTest(named_in):
                done = self.run_with(arguments[0], "--version-source", "gradle.properties", *arguments[1:])
                self.assertEqual(done.returncode, 1)
                self.assertNotIn("Traceback", done.stderr)
                self.assertIn(named_in, done.stderr)


class TheNextCommand(unittest.TestCase):
    def test_what_follows_is_bare_and_the_source_adds_its_marker(self):
        """`-SNAPSHOT` is Gradle's marker for a version being worked on.
        A repository versioned by its tags has no such state, so what follows a release there is the bare version.
        That is also what `version` takes under `tags` when no version is given."""
        self.assertEqual(self.next_after("v0.1.1", "gradle.properties"), ([], "0.1.2-SNAPSHOT"))
        self.assertEqual(self.next_after("v0.1.1", "tags"), ([], "0.1.2"))

    def next_after(self, released, source):
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            problems = main.next_command(argparse.Namespace(released=released, version_source=source,
                                                                     tag_prefix="v"))
        return problems, printed.getvalue().strip()


class TheChannelCommand(unittest.TestCase):
    def test_a_version_is_asked_about_bare(self):
        """channel takes no tag prefix, so a tag's name is refused rather than read with the prefix guessed."""
        for version, answer in (("0.3.0-beta.1", ([], "beta\n")),
                                ("v0.3.0-beta.1", (["'v0.3.0-beta.1' is not a version; channel takes one "
                                                    "without the tag prefix"], ""))):
            with self.subTest(version=version):
                printed = io.StringIO()
                with contextlib.redirect_stdout(printed):
                    problems = main.channel_command(argparse.Namespace(version=version))
                self.assertEqual((problems, printed.getvalue()), answer)


class TheOptions(unittest.TestCase):
    def test_a_command_refuses_the_options_it_never_reads(self):
        """notes and channel read neither option, and set-version names no tag, so it takes no --tag-prefix."""
        for arguments in (["notes", "0.1.0", "--version-source", "tags"], ["notes", "0.1.0", "--tag-prefix", "v"],
                          ["channel", "0.1.0", "--version-source", "tags"], ["channel", "0.1.0", "--tag-prefix", "v"],
                          ["set-version", "0.1.0", "--version-source", "tags", "--tag-prefix", "v"]):
            with self.subTest(arguments=arguments):
                done = subprocess.run([sys.executable, str(SCRIPT), *arguments], capture_output=True, text=True)
                self.assertEqual(done.returncode, 2, done.stderr)
                self.assertIn("unrecognized arguments", done.stderr)
