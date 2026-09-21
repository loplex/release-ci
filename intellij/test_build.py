#!/usr/bin/env python3
"""What the build stops on: a Plugin Verifier that left no report, and anything but exactly one signed archive
where it says the archive landed.

Run with `python3 -m unittest discover` over the directory this file sits in.
"""

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ARCHIVE_SH = Path(__file__).resolve().parent / "build" / "archive.sh"
VERIFIER_REPORT_SH = ARCHIVE_SH.parent / "verifier-report.sh"
# The pattern a caller gets unless it sets `archive-pattern`, read from the action rather than copied, so that the
# archive picked here is the one the action picks.
DEFAULT_PATTERN = re.search(r"^  archive-pattern:\n(?:    .*\n)*?    default: (.+)$",
                            (ARCHIVE_SH.parent / "action.yml").read_text(encoding="utf-8"), re.MULTILINE).group(1)


class TheSignedArchive(unittest.TestCase):
    def setUp(self):
        self.work = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        (self.work / "build" / "distributions").mkdir(parents=True)

    def made(self, *names):
        for name in names:
            (self.work / "build" / "distributions" / name).write_bytes(b"an archive")

    def run_archive_sh(self, pattern=DEFAULT_PATTERN):
        written = self.work / "output.txt"
        written.write_text("", encoding="utf-8")
        done = subprocess.run(["bash", str(ARCHIVE_SH)], cwd=self.work, capture_output=True, text=True,
                              env={**os.environ, "ARCHIVE_PATTERN": pattern, "GITHUB_OUTPUT": str(written)})
        return done, written.read_text(encoding="utf-8")

    def test_the_one_signed_archive_is_named(self):
        self.made("plugin-1.0.0.zip", "plugin-1.0.0-signed.zip")
        done, output = self.run_archive_sh()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(output, "archive=build/distributions/plugin-1.0.0-signed.zip\n")

    def test_none_is_refused(self):
        done, output = self.run_archive_sh()
        self.assertEqual(done.returncode, 1)
        self.assertIn("matched 0 file(s)", done.stdout)
        self.assertEqual(output, "")

    def test_several_are_refused_rather_than_one_picked(self):
        self.made("a-signed.zip", "b-signed.zip")
        done, output = self.run_archive_sh()
        self.assertEqual(done.returncode, 1)
        self.assertIn("matched 2 file(s)", done.stdout)
        self.assertEqual(output, "")

    def test_a_path_naming_no_file_is_refused(self):
        """No glob character, so nothing for nullglob to act on: the path comes back as itself, one word
        and no file."""
        done, output = self.run_archive_sh("build/distributions/plugin-signed.zip")
        self.assertEqual(done.returncode, 1)
        self.assertIn("names no file here", done.stdout)
        self.assertNotIn("matched 1 file(s)", done.stdout)
        self.assertEqual(output, "")

    def test_a_pattern_holding_a_space_is_one_pattern(self):
        """An archive named after a project called "My Plugin" is found whole, rather than taken for two words
        naming no file."""
        self.made("My Plugin-1.0.0-signed.zip")
        done, output = self.run_archive_sh("build/distributions/My Plugin-*-signed.zip")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(output, "archive=build/distributions/My Plugin-1.0.0-signed.zip\n")


class TheVerifierReport(unittest.TestCase):
    def setUp(self):
        self.work = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.reports = self.work / "build" / "reports" / "pluginVerifier"

    def run_verifier_report_sh(self):
        return subprocess.run(["bash", str(VERIFIER_REPORT_SH)], cwd=self.work, capture_output=True, text=True)

    def test_a_build_that_left_a_report_goes_on(self):
        (self.reports / "IC-243.21565.193").mkdir(parents=True)
        (self.reports / "IC-243.21565.193" / "report.md").write_text("Compatible\n", encoding="utf-8")
        done = self.run_verifier_report_sh()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_a_build_that_left_no_report_stops(self):
        done = self.run_verifier_report_sh()
        self.assertEqual(done.returncode, 1)
        self.assertIn("left no report in build/reports/pluginVerifier", done.stdout)

    def test_an_empty_report_directory_is_no_report(self):
        """What a Verifier that never ran can leave behind: the directory, made by the build, and nothing in it."""
        self.reports.mkdir(parents=True)
        done = self.run_verifier_report_sh()
        self.assertEqual(done.returncode, 1)
        self.assertIn("left no report", done.stdout)


if __name__ == "__main__":
    unittest.main()
