#!/usr/bin/env python3
"""What warn writes into a release's notes, tested against a stub `gh`.

The stub answers `release view` with notes a test stages, and keeps what `release edit` would have written.
Nothing is sent anywhere, and the notes can be compared byte for byte.

Run with `python3 -m unittest discover -s release-flow` from the repository root.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

WARN = Path(__file__).resolve().parent.parent / "warn" / "warn.py"

RUN = "https://github.com/o/r/actions/runs/7"
START, END = "<!-- release-flow/warn -->", "<!-- /release-flow/warn -->"
NOTES = "### Fixed\n\n- F\n"

STUB = r'''#!/bin/bash
here="$(dirname "$0")"
printf '%s\n' "$*" >> "$here/said.txt"
case "$1 $2" in
  "release view") [[ -f $here/view.json ]] || { echo "release not found" >&2; exit 1; }; cat "$here/view.json" ;;
  "release edit")
    [[ -f $here/refuse ]] && exit 1
    while (( $# > 0 )); do [[ $1 == --notes-file ]] && cp "$2" "$here/written.md"; shift; done ;;
esac
exit 0
'''


class Warn(unittest.TestCase):

    def setUp(self):
        self.stubs = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        (self.stubs / "gh").write_text(STUB, encoding="utf-8")
        (self.stubs / "gh").chmod(0o755)

    def warn(self, outcome, notes=NOTES, to="the JetBrains Marketplace"):
        if notes is not None:
            (self.stubs / "view.json").write_text(json.dumps({"body": notes}), encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(WARN)], capture_output=True, text=True,
            env={**os.environ, "PATH": f"{self.stubs}:{os.environ['PATH']}",
                 "OUTCOME": outcome, "TAG": "v0.1.1", "TO": to, "RUN": RUN, "GH_TOKEN": "stub"},
        )

    def written(self):
        path = self.stubs / "written.md"
        return path.read_bytes().decode("utf-8") if path.exists() else None

    def edited(self):
        path = self.stubs / "said.txt"
        said = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        return [line for line in said if line.startswith("release edit")]

    def warned(self, outcome="failure", notes=NOTES):
        done = self.warn(outcome, notes)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        return self.written()

    def test_a_failed_publish_puts_the_warning_on_top_of_the_notes(self):
        written = self.warned()
        self.assertTrue(written.startswith("<!-- release-flow/warn -->\n> [!WARNING]\n"), written)
        self.assertIn("Publishing this release to the JetBrains Marketplace did not complete", written)
        self.assertIn(f"[the run]({RUN})", written)
        self.assertTrue(written.endswith("<!-- /release-flow/warn -->\n\n" + NOTES), written)
        self.assertEqual(self.edited(), [self.edited()[0]])
        self.assertTrue(self.edited()[0].startswith("release edit v0.1.1 --notes-file "))

    def test_a_publish_that_did_not_run_warns_as_one_that_failed(self):
        """The step before it failed, such as taking the archive off the release, so nothing was published."""
        self.assertEqual(self.warned("skipped"), self.warned("failure"))

    def test_a_warning_is_one_sentence_to_a_line(self):
        """GitHub shows a line end in release notes as a line break, so a wrapped sentence would show broken."""
        for line in self.warned().splitlines():
            if line.startswith("> ") and line != "> [!WARNING]":
                self.assertEqual(line.count(". "), 0, line)
                self.assertTrue(line.endswith("."), line)

    def test_a_publish_that_completes_takes_the_warning_off_and_gives_back_the_notes(self):
        warned = self.warned()
        self.assertEqual(self.warned("success", warned), NOTES)

    def test_notes_edited_in_the_browser_keep_their_line_ends(self):
        """GitHub stores notes as they were sent, CRLF included.

        The warning is written with their line ends, and taking it off gives them back byte for byte.
        """
        notes = NOTES.replace("\n", "\r\n")
        warned = self.warned(notes=notes)
        self.assertNotIn("\n", warned.replace("\r\n", ""), repr(warned))
        self.assertEqual(self.warned("success", warned), notes)

    def test_notes_that_do_not_end_a_line_come_back_as_they_were(self):
        notes = NOTES.rstrip("\n")
        self.assertEqual(self.warned("success", self.warned(notes=notes)), notes)

    def test_notes_that_were_the_warning_alone_come_back_empty(self):
        warned = self.warned(notes="")
        self.assertTrue(warned.endswith("<!-- /release-flow/warn -->\n"), warned)
        self.assertEqual(self.warned("success", warned), "")

    def test_a_run_that_fails_again_leaves_the_notes_alone(self):
        warned = self.warned()
        (self.stubs / "written.md").unlink()
        (self.stubs / "said.txt").unlink()
        done = self.warn("failure", warned)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.edited(), [])

    def test_a_warning_in_other_words_is_replaced_by_this_one(self):
        """Found by its markers, not its wording, so a warning written by another version is not repeated."""
        older = "<!-- release-flow/warn -->\n> [!WARNING]\n> Older words.\n<!-- /release-flow/warn -->\n\n" + NOTES
        written = self.warned(notes=older)
        self.assertNotIn("Older words", written)
        self.assertEqual(written.count("<!-- release-flow/warn -->"), 1, written)
        self.assertEqual(written, self.warned())

    def test_notes_without_a_warning_are_left_alone_once_publishing_completes(self):
        done = self.warn("success")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.edited(), [])

    def test_a_warning_the_notes_carry_of_their_own_is_theirs(self):
        own = "> [!WARNING]\n> Did not complete, on purpose.\n\n" + NOTES
        done = self.warn("success", own)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.edited(), [])
        self.assertTrue(self.warned(notes=own).endswith("-->\n\n" + own))

    def test_a_marker_anywhere_but_at_the_start_stops_the_run(self):
        """A marker on a line of its own is looked for only where this action puts one.

        Anywhere else it may be an example shown as code, or the warning after someone wrote above it.
        Neither is guessed at.
        """
        warning = f"{START}\n> [!WARNING]\n> x\n{END}\n\n"
        cases = {
            "the warning, below text written above it": "Read this first.\n\n" + warning + NOTES,
            "an example shown in a fenced block": NOTES + f"\n```\n{START}\n> x\n{END}\n```\n",
            "an example indented as code": NOTES + f"\nShown as:\n\n    {START}\n",
            "an opening marker alone": NOTES + f"\n{START}\n",
            "a closing marker alone": NOTES + f"\n{END}\n",
        }
        self.assert_left_alone(cases, "where this action does not put one")
        self.assert_left_alone({
            "the warning, indented, at the start": "  " + warning + NOTES,
            "the warning, with spaces after its marker": warning.replace("-->", "-->  ", 1) + NOTES,
        }, "not as this action writes it")
        self.assert_left_alone({"a marker below the warning at the start": warning + NOTES + f"\n```\n{START}\n```\n"},
                               "as well, below the one at their start")

    def test_the_line_holding_the_marker_is_named(self):
        done = self.warn("success", f"Read this first.\n\n{START}\n> x\n{END}\n\n" + NOTES)
        self.assertIn("on line 3,", done.stdout)

    def test_a_warning_at_the_start_that_does_not_read_as_this_action_s_stops_the_run(self):
        """Two cases.

        Not closed: taking it off would take the notes' own text with it.
        Holding more than quoted lines: it is not what this action writes.
        """
        cases = {
            "not closed": f"{START}\n> [!WARNING]\n\n" + NOTES,
            "holding a line that is not quoted": f"{START}\n> [!WARNING]\nThe notes' own.\n{END}\n\n" + NOTES,
            "opened twice": f"{START}\n> x\n{START}\n{END}\n\n" + NOTES,
        }
        self.assert_left_alone(cases, "does not read as this action's")

    def assert_left_alone(self, cases, said):
        for case, notes in cases.items():
            for outcome in ("success", "failure"):
                with self.subTest(case=case, outcome=outcome):
                    (self.stubs / "said.txt").unlink(missing_ok=True)
                    done = self.warn(outcome, notes)
                    self.assertNotEqual(done.returncode, 0)
                    self.assertIn(said, done.stdout)
                    self.assertEqual(self.edited(), [])

    def test_a_marker_mentioned_in_a_line_of_text_is_text(self):
        """Only a line holding a marker alone, apart from spaces and tabs, counts as a marker.

        A line ends where CommonMark ends one: at a line feed, a carriage return, or both.
        Only spaces and tabs indent it.
        So a form feed or a Unicode line separator does not set a marker apart.
        """
        cases = {
            "a line holding more than a marker": f"Written as {START}\n",
            "a line only a Unicode line separator would end": f"Written as\u2028{START}\n",
            "a line only a form feed would end": f"Written as\x0c{START}\n",
            "a line a Unicode line separator would indent": f"\u2028{START}\n",
            "a line a form feed would indent": f"\x0c{START}\n",
        }
        for case, text in cases.items():
            with self.subTest(case=case):
                notes = NOTES + "\n" + text
                self.assertEqual(self.warned("success", self.warned(notes=notes)), notes)

    def test_notes_ended_by_carriage_returns_alone_keep_them(self):
        """A carriage return alone ends a line in CommonMark, and the warning uses the notes' own line ends."""
        notes = NOTES.replace("\n", "\r")
        warned = self.warned(notes=notes)
        self.assertNotIn("\n", warned, repr(warned))
        self.assertEqual(self.warned("success", warned), notes)

    def test_only_a_blank_line_after_the_warning_goes_with_it(self):
        """A blank line as CommonMark defines it: nothing on it but spaces and tabs.

        A form feed is text.
        """
        notes = self.warned().replace("-->\n\n", "-->\n\x0c\n", 1)
        self.assertEqual(self.warned("success", notes), "\x0c\n" + NOTES)

    def test_an_outcome_that_names_no_step_stops_the_run(self):
        """`steps.<id>.outcome` is empty for an id that names no step.

        Read as a failure, it would warn on every release.
        """
        done = self.warn("")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("does steps.<id> name the step that publishes?", done.stdout)
        self.assertEqual(self.edited(), [])

    def test_an_outcome_but_success_failure_or_skipped_stops_the_run(self):
        """`cancelled` included: a step has that outcome only in a cancelled run, where this does not run."""
        for outcome in ("cancelled", "Failure"):
            with self.subTest(outcome=outcome):
                done = self.warn(outcome)
                self.assertNotEqual(done.returncode, 0)
                self.assertIn(f"outcome is '{outcome}'", done.stdout)
                self.assertEqual(self.edited(), [])

    def test_what_the_release_is_published_to_has_to_be_said_on_one_line(self):
        """A line end would show as a line break halfway through the sentence.

        It would also leave an unquoted line in the warning, and the next run would not take it for this action's.
        """
        for to in ("", " ", "the JetBrains\nMarketplace", "the JetBrains\rMarketplace"):
            with self.subTest(to=to):
                done = self.warn("failure", to=to)
                self.assertNotEqual(done.returncode, 0)
                self.assertIn("has to say, on one line", done.stdout)
                self.assertEqual(self.edited(), [])

    def test_notes_that_cannot_be_read_stop_the_run(self):
        done = self.warn("failure", notes=None)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("could not be read", done.stdout)
        self.assertEqual(self.edited(), [])

    def test_notes_that_cannot_be_written_stop_the_run(self):
        (self.stubs / "refuse").touch()
        done = self.warn("failure")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("could not be written", done.stdout)


if __name__ == "__main__":
    unittest.main()
