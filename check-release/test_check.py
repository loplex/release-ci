#!/usr/bin/env python3
"""What the action does with its inputs, exercised against a repository built for the purpose: which checks it
runs, how it reads the prefix it is given, and what it says `version` answered.

Run with `python3 -m unittest discover` over the directory this file sits in.
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

CHECK = Path(__file__).resolve().parent / "check.sh"


def git(*arguments, cwd):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *arguments], cwd=cwd, check=True,
                          capture_output=True, text=True)


class TheAction(unittest.TestCase):
    """A repository with one release, 0.1.0, tagged the way the test asks."""

    def repository(self, tag="v0.1.0"):
        self.work = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        git("init", "-q", "-b", "main", cwd=self.work)
        (self.work / "CHANGELOG.md").write_text("# Changelog\n\n## [0.1.0] - 2026-09-01\n\n- A\n", encoding="utf-8")
        git("add", "-A", cwd=self.work)
        git("commit", "-qm", "0.1.0", cwd=self.work)
        git("tag", tag, cwd=self.work)

    def setUp(self):
        self.repository()

    def check(self, checks, tag_prefix="v", version=""):
        written = Path(self.enterContext(tempfile.TemporaryDirectory())) / "output.txt"
        written.write_text("", encoding="utf-8")
        done = subprocess.run(
            ["bash", str(CHECK)], cwd=self.work, capture_output=True, text=True,
            env={**os.environ, "SOURCE": "tags", "TAG_PREFIX": tag_prefix, "CHECKS": checks, "VERSION": version,
                 "GITHUB_OUTPUT": str(written)},
        )
        outputs = dict(
            line.split("=", 1) for line in written.read_text(encoding="utf-8").splitlines() if "=" in line
        )
        return done, outputs

    def test_the_checks_asked_for_run_and_pass(self):
        done, _ = self.check("changelog ancestry")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("Compared 1 released section(s)", done.stdout)
        self.assertIn("All 1 released tag(s) are reachable", done.stdout)

    def test_a_check_that_says_no_fails_the_run_and_is_named(self):
        done, outputs = self.check("version", version="0.4.0")
        self.assertEqual(done.returncode, 1)
        self.assertIn("::error::check-release version said no", done.stdout)
        self.assertEqual(outputs, {})

    def test_a_name_that_is_no_check_fails_before_anything_runs(self):
        """A typo skipped would be a check nobody notices was not run."""
        done, _ = self.check("ancestry ancestory")
        self.assertEqual(done.returncode, 1)
        self.assertIn("'ancestory' is not a check this action runs", done.stdout)
        self.assertNotIn("reachable", done.stdout)

    def test_asking_for_no_check_at_all_fails(self):
        for checks in ("", " ", "\n"):
            with self.subTest(checks=checks):
                done, _ = self.check(checks)
                self.assertEqual(done.returncode, 1)
                self.assertIn("no check was asked for", done.stdout)

    def test_none_says_the_tags_carry_no_prefix(self):
        """`^none` handed on as a prefix of its own would count no release at all, and pass having compared
        nothing."""
        self.repository(tag="0.1.0")
        done, _ = self.check("ancestry", tag_prefix="^none")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("All 1 released tag(s) are reachable", done.stdout)

    def test_version_says_what_may_be_released_and_where_it_goes(self):
        for asked, channel in (("0.2.0", "default"), ("0.2.0-beta.1", "beta")):
            with self.subTest(asked=asked):
                done, outputs = self.check("version", version=asked)
                self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
                self.assertEqual(outputs, {"version": asked, "channel": channel})


if __name__ == "__main__":
    unittest.main()
