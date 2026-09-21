#!/usr/bin/env python3
"""Where the build says the signed archive landed: exactly one file, or the run stops.

Run with `python3 -m unittest discover` over the directory this file sits in.
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ARCHIVE = Path(__file__).resolve().parent / "build" / "archive.sh"


class TheSignedArchive(unittest.TestCase):
    def setUp(self):
        self.work = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        (self.work / "build" / "distributions").mkdir(parents=True)

    def made(self, *names):
        for name in names:
            (self.work / "build" / "distributions" / name).write_bytes(b"an archive")

    def archive(self, pattern="build/distributions/*-signed.zip"):
        written = self.work / "output.txt"
        written.write_text("", encoding="utf-8")
        done = subprocess.run(["bash", str(ARCHIVE)], cwd=self.work, capture_output=True, text=True,
                              env={**os.environ, "PATTERN": pattern, "GITHUB_OUTPUT": str(written)})
        return done, written.read_text(encoding="utf-8")

    def test_the_one_signed_archive_is_named(self):
        self.made("plugin-1.0.0.zip", "plugin-1.0.0-signed.zip")
        done, output = self.archive()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(output, "archive=build/distributions/plugin-1.0.0-signed.zip\n")

    def test_none_is_refused(self):
        done, output = self.archive()
        self.assertEqual(done.returncode, 1)
        self.assertIn("matched 0 file(s)", done.stdout)
        self.assertEqual(output, "")

    def test_several_are_refused_rather_than_one_picked(self):
        self.made("a-signed.zip", "b-signed.zip")
        done, output = self.archive()
        self.assertEqual(done.returncode, 1)
        self.assertIn("matched 2 file(s)", done.stdout)
        self.assertEqual(output, "")

    def test_a_path_naming_no_file_is_refused(self):
        """No glob character, so nullglob hands the path back as itself: one word, and no file."""
        done, output = self.archive("build/distributions/plugin-signed.zip")
        self.assertEqual(done.returncode, 1)
        self.assertIn("names no file here", done.stdout)
        self.assertNotIn("matched 1 file(s)", done.stdout)
        self.assertEqual(output, "")


if __name__ == "__main__":
    unittest.main()
