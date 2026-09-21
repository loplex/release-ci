#!/usr/bin/env python3
"""What draft does to a repository and asks of GitHub, exercised against a repository built for the purpose.

A bare repository stands in for the remote, so the forced push is a real push. `gh` is a stub on PATH that
records what it is asked and answers `release view` from a file, so that a draft left by an earlier run can
be staged; nothing is sent anywhere.

Run with `python3 -m unittest discover` over the directory this file sits in.
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

DRAFT = Path(__file__).resolve().parent / "draft" / "draft.sh"

CUT = "# Changelog\n\n## [Unreleased]\n\n## [0.1.1] - 2026-09-21\n\n### Fixed\n\n- F\n\n## [0.1.0] - 2026-09-01\n\n- old\n"

STUB = r'''#!/bin/bash
here="$(dirname "$0")"
printf '%s\n' "$*" >> "$here/said.txt"
case "$1 $2" in
  "release view") [ -f "$here/isDraft" ] && cat "$here/isDraft" && exit 0; exit 1 ;;
  "release delete")
    left=$(( $(cat "$here/drafts" 2>/dev/null || echo 1) - 1 ))
    echo "$left" > "$here/drafts"
    [ "$left" -gt 0 ] || rm -f "$here/isDraft" ;;
  "release create")
    while [ $# -gt 0 ]; do [ "$1" = --notes-file ] && cp "$2" "$here/notes.txt"; shift; done ;;
esac
exit 0
'''


def git(*arguments, cwd, check=True):
    return subprocess.run(["git", *arguments], cwd=cwd, check=check, capture_output=True, text=True)


class Draft(unittest.TestCase):
    """A release commit cut and built, the workspace on it, waiting to be pushed and drafted."""

    def setUp(self):
        self.cut()

    def cut(self, version="0.1.1", changelog=CUT):
        root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.origin, self.work, self.stubs = root / "origin.git", root / "work", root / "bin"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.origin)], check=True)
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.work)], check=True, capture_output=True)
        for name, value in (("user.email", "t@t"), ("user.name", "t")):
            git("config", name, value, cwd=self.work)
        (self.work / "gradle.properties").write_text("version = 0.1.1-SNAPSHOT\ntagPrefix = v\n", encoding="utf-8")
        (self.work / "CHANGELOG.md").write_text("# Changelog\n\n## [Unreleased]\n", encoding="utf-8")
        git("add", "-A", cwd=self.work)
        git("commit", "-qm", "base", cwd=self.work)
        git("push", "-q", "-u", "origin", "main", cwd=self.work)
        git("switch", "-qc", f"release/{version}", cwd=self.work)
        (self.work / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
        git("commit", "-qam", f"chore(release): {version}", cwd=self.work)
        (self.work / "build").mkdir()
        (self.work / "build" / "plugin-signed.zip").write_text("an archive", encoding="utf-8")
        self.stubs.mkdir()
        (self.stubs / "gh").write_text(STUB, encoding="utf-8")
        (self.stubs / "gh").chmod(0o755)
        self.version = version

    def draft(self, files="build/*-signed.zip"):
        return subprocess.run(
            ["bash", str(DRAFT)], cwd=self.work, capture_output=True, text=True,
            env={**os.environ, "PATH": f"{self.stubs}:{os.environ['PATH']}",
                 "SOURCE": "gradle.properties", "TAG_PREFIX": "", "VERSION": self.version,
                 "TAG": f"v{self.version}", "BRANCH": f"release/{self.version}", "FILES": files, "GH_TOKEN": "stub"},
        )

    def said(self):
        path = self.stubs / "said.txt"
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    def created(self):
        return next((line for line in self.said() if line.startswith("release create")), None)

    def on_origin(self, branch):
        return git("rev-parse", "--verify", "-q", f"refs/heads/{branch}", cwd=self.origin, check=False).stdout.strip()

    def test_the_branch_is_pushed_and_the_release_drafted_at_its_commit(self):
        done = self.draft()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        head = git("rev-parse", "HEAD", cwd=self.work).stdout.strip()
        self.assertEqual(self.on_origin("release/0.1.1"), head)
        created = self.created()
        self.assertIsNotNone(created)
        for part in ("release create v0.1.1", "--draft", f"--target {head}", "--title v0.1.1", "build/plugin-signed.zip"):
            self.assertIn(part, created)

    def test_the_notes_are_the_released_section(self):
        self.draft()
        self.assertEqual((self.stubs / "notes.txt").read_text(encoding="utf-8"), "### Fixed\n\n- F\n")

    def test_a_final_release_is_not_marked_as_a_pre_release(self):
        self.draft()
        self.assertNotIn("--prerelease", self.created())

    def test_a_pre_release_is_marked_as_one(self):
        """So that GitHub does not hold it out as the latest release to everyone."""
        self.cut("0.2.0-rc.1", CUT.replace("0.1.1", "0.2.0-rc.1"))
        done = self.draft()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("--prerelease", self.created())

    def test_a_draft_left_by_an_earlier_run_goes_first(self):
        """GitHub would put a second draft beside it rather than replace it."""
        (self.stubs / "isDraft").write_text("true\n", encoding="utf-8")
        self.draft()
        said = self.said()
        deleted = next(index for index, line in enumerate(said) if line.startswith("release delete v0.1.1"))
        self.assertLess(deleted, said.index(self.created()))

    def test_every_draft_left_by_earlier_runs_goes(self):
        """`gh` finds one draft of a tag at a time, so two left by two runs take two deletions."""
        (self.stubs / "isDraft").write_text("true\n", encoding="utf-8")
        (self.stubs / "drafts").write_text("2\n", encoding="utf-8")
        done = self.draft()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(len([line for line in self.said() if line.startswith("release delete v0.1.1")]), 2)
        self.assertIsNotNone(self.created())

    def test_a_published_release_is_not_this_run_s_to_remove(self):
        (self.stubs / "isDraft").write_text("false\n", encoding="utf-8")
        self.draft()
        self.assertFalse([line for line in self.said() if line.startswith("release delete")])

    def test_a_second_attempt_replaces_the_branch(self):
        """The one forced push in the flow. The attempts differ in content, as a real second attempt does:
        two identical commits in the same second are one commit, and pushing it again proves nothing."""
        self.draft()
        first = self.on_origin("release/0.1.1")
        git("reset", "-q", "--hard", "HEAD~1", cwd=self.work)
        (self.work / "CHANGELOG.md").write_text(CUT.replace("- F\n", "- F\n- G, found after the first draft\n"),
                                                encoding="utf-8")
        git("commit", "-qam", "chore(release): 0.1.1", cwd=self.work)
        done = self.draft()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertNotEqual(self.on_origin("release/0.1.1"), first)

    def test_a_pattern_matching_nothing_stops_the_run_before_anything_is_pushed(self):
        done = self.draft(files="build/*-signed.zip build/nothing-*.zip")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("build/nothing-*.zip matches nothing", done.stdout + done.stderr)
        self.assertEqual(self.on_origin("release/0.1.1"), "")
        self.assertIsNone(self.created())

    def test_a_path_naming_no_file_stops_the_run_before_anything_is_pushed(self):
        """A plain path has no glob character for nullglob to act on, so it comes back as itself, and a build
        that names the one file it made hands over exactly that."""
        done = self.draft(files="build/plugin-signed.zip build/missing.zip")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("build/missing.zip is no file here", done.stdout + done.stderr)
        self.assertEqual(self.on_origin("release/0.1.1"), "")
        self.assertIsNone(self.created())

    def test_a_directory_is_no_file_to_attach(self):
        done = self.draft(files="build")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("build is no file here", done.stdout + done.stderr)
        self.assertEqual(self.on_origin("release/0.1.1"), "")
        self.assertIsNone(self.created())

    def test_a_section_with_nothing_to_say_stops_the_run_before_anything_is_pushed(self):
        self.cut(changelog=CUT.replace("### Fixed\n\n- F\n\n", ""))
        done = self.draft()
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(self.on_origin("release/0.1.1"), "")
        self.assertIsNone(self.created())

    def test_nothing_to_attach_is_allowed(self):
        done = self.draft(files="")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertTrue(self.created().rstrip().endswith("--notes-file " + self.created().split("--notes-file ")[1].split()[0]))


if __name__ == "__main__":
    unittest.main()
