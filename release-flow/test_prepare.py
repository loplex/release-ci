#!/usr/bin/env python3
"""What prepare does to a repository, exercised against one built for the purpose.

A bare repository stands in for the remote, so that nothing reaching it is seen not to - prepare pushes
nothing, the build running from its commit next. Nothing here needs `gh`: prepare stops before anything is
drafted.

Run with `python3 -m unittest discover` over the directory this file sits in.
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

PREPARE = Path(__file__).resolve().parent / "prepare" / "prepare.sh"

PENDING = "# Changelog\n\n## [Unreleased]\n\n### Added\n\n- A\n\n## [0.1.0] - 2026-09-01\n\n- old\n"


def git(*arguments, cwd, check=True):
    return subprocess.run(["git", *arguments], cwd=cwd, check=check, capture_output=True, text=True)


class Staged(unittest.TestCase):
    """A repository between releases: 0.1.0 tagged, work under [Unreleased], and the next version declared
    with its marker where the source declares one."""

    def stage(self, declared="version = 0.1.1-SNAPSHOT\ntagPrefix = v\n", changelog=PENDING, tag="v0.1.0"):
        root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.origin = root / "origin.git"
        self.work = root / "work"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.origin)], check=True)
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.work)], check=True,
                       capture_output=True)
        for name, value in (("user.email", "t@t"), ("user.name", "t")):
            git("config", name, value, cwd=self.work)
        (self.work / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
        if declared is not None:
            (self.work / "gradle.properties").write_text(declared, encoding="utf-8")
        git("add", "-A", cwd=self.work)
        git("commit", "-qm", "0.1.0 and work since", cwd=self.work)
        git("tag", tag, cwd=self.work)
        git("push", "-q", "-u", "origin", "main", tag, cwd=self.work)

    def setUp(self):
        self.stage()

    def prepare(self, source="gradle.properties", tag_prefix="", version="", repository_url=""):
        written = Path(self.enterContext(tempfile.TemporaryDirectory())) / "output.txt"
        written.write_text("", encoding="utf-8")
        done = subprocess.run(
            ["bash", str(PREPARE)], cwd=self.work, capture_output=True, text=True,
            env={**os.environ, "SOURCE": source, "TAG_PREFIX": tag_prefix, "VERSION": version,
                 "BRANCH_PREFIX": "release/", "REPOSITORY_URL": repository_url, "GITHUB_OUTPUT": str(written)},
        )
        outputs = dict(
            line.split("=", 1) for line in written.read_text(encoding="utf-8").splitlines() if "=" in line
        )
        return outputs, done

    def on_origin(self, branch):
        return git("rev-parse", "--verify", "-q", f"refs/heads/{branch}", cwd=self.origin, check=False)

    def file_on(self, branch, name):
        return git("show", f"{branch}:{name}", cwd=self.work).stdout

    def release_branches(self):
        return git("branch", "--list", "release/*", cwd=self.work).stdout.strip()


class Prepare(Staged):
    def test_the_release_commit_lands_on_a_branch_of_its_own(self):
        outputs, done = self.prepare()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(outputs, {"version": "0.1.1", "tag": "v0.1.1", "branch": "release/0.1.1"})
        self.assertEqual(git("branch", "--show-current", cwd=self.work).stdout.strip(), "release/0.1.1",
                         "the build runs from the release commit next, so the workspace is left on it")
        self.assertIn("chore(release): 0.1.1", git("log", "-1", "--format=%s", cwd=self.work).stdout)

    def test_nothing_reaches_the_remote(self):
        """A build that fails after this should leave neither a branch nor a draft: pushing waits for it."""
        self.prepare()
        self.assertNotEqual(self.on_origin("release/0.1.1").returncode, 0)

    def test_the_link_definitions_are_written_where_the_repository_is_given(self):
        self.prepare(repository_url="https://example.invalid/r")
        changelog = self.file_on("release/0.1.1", "CHANGELOG.md")
        self.assertIn("[0.1.1]: https://example.invalid/r/compare/v0.1.0...v0.1.1\n", changelog)

    def test_the_marker_comes_off_the_declared_version(self):
        self.prepare()
        self.assertIn("version = 0.1.1\n", self.file_on("release/0.1.1", "gradle.properties"))

    def test_the_pending_entries_become_the_released_section(self):
        self.prepare()
        changelog = self.file_on("release/0.1.1", "CHANGELOG.md")
        self.assertIn("## [0.1.1] - ", changelog)
        self.assertIn("### Added\n\n- A\n", changelog)
        self.assertRegex(changelog, r"## \[Unreleased\]\n\n## \[0\.1\.1\]")  # Nothing is left pending.

    def test_the_default_branch_is_not_touched(self):
        before = git("rev-parse", "main", cwd=self.origin).stdout
        self.prepare()
        self.assertEqual(git("rev-parse", "main", cwd=self.origin).stdout, before)

    def test_a_source_declaring_no_version_releases_what_it_is_handed(self):
        self.stage(declared=None)
        outputs, done = self.prepare(source="tags", tag_prefix="v", version="0.2.0")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(outputs["tag"], "v0.2.0")
        self.assertIn("declares no version", done.stdout)
        self.assertIn("## [0.2.0] - ", self.file_on("release/0.2.0", "CHANGELOG.md"))

    def test_a_source_declaring_no_version_defaults_to_the_version_after_the_highest(self):
        """A patch here because 0.1.0 is a final release. What follows an open pre-release train is the
        release it was heading for, which is `next` to answer and not this."""
        self.stage(declared=None)
        outputs, done = self.prepare(source="tags", tag_prefix="v")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(outputs["version"], "0.1.1")

    def test_none_says_the_tags_carry_no_prefix(self):
        """Handed on as a prefix of its own, `^none` would count no release, and there would be nothing to
        count the default from."""
        self.stage(declared=None, tag="0.1.0")
        outputs, done = self.prepare(source="tags", tag_prefix="^none")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual((outputs["version"], outputs["tag"]), ("0.1.1", "0.1.1"))

    def test_a_second_attempt_at_the_same_version_starts_again(self):
        """A branch left by an earlier attempt is replaced rather than continued, so the release commit is
        still the one commit on top of the default branch."""
        self.prepare()
        git("switch", "-q", "main", cwd=self.work)
        outputs, done = self.prepare()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(git("rev-list", "--count", "main..release/0.1.1", cwd=self.work).stdout.strip(), "1")


class NothingIsCutWhereTheRulesSayNo(Staged):
    """A release that fails the rules is one that was never cut, not one that has to be undone: no release
    branch, no output, and the workspace still on the default branch. A version that cannot be written is the
    one exception, the branch being cut after the changelog is closed and before the version is written: it
    leaves the branch, with no commit on it, and the next attempt at the version replaces it."""

    def assert_nothing_was_cut(self, outputs, done, saying):
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(outputs, {})
        self.assertIn(saying, done.stdout + done.stderr)
        self.assertEqual(self.release_branches(), "", "no release branch is cut where the rules say no")
        self.assertEqual(git("branch", "--show-current", cwd=self.work).stdout.strip(), "main")

    def test_a_version_the_step_refuses(self):
        outputs, done = self.prepare(version="0.4.0-SNAPSHOT")
        self.assert_nothing_was_cut(outputs, done, "does not follow 0.1.0")

    def test_a_version_that_is_not_marked_as_being_worked_on(self):
        outputs, done = self.prepare(version="0.1.1")
        self.assert_nothing_was_cut(outputs, done, "not a version being worked on")

    def test_a_released_section_that_was_edited(self):
        (self.work / "CHANGELOG.md").write_text(PENDING.replace("- old", "- old, said better"), encoding="utf-8")
        git("commit", "-qam", "edit", cwd=self.work)
        git("push", "-q", "origin", "main", cwd=self.work)
        outputs, done = self.prepare()
        self.assert_nothing_was_cut(outputs, done, "no longer reads as the tag has it")

    def test_a_version_that_cannot_be_written(self):
        """Declared twice, which the writer refuses. Read as a source declaring nothing, the release commit
        would still carry -SNAPSHOT on the line Gradle reads, and the build would make a snapshot of it."""
        self.stage(declared="version = 0.1.1-SNAPSHOT\nversion = 0.1.1-SNAPSHOT\ntagPrefix = v\n")
        outputs, done = self.prepare()
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertEqual(outputs, {})
        self.assertIn("could not be given 0.1.1", done.stdout)
        self.assertIn("release/0.1.1", self.release_branches(), "the branch was cut before the write failed")
        self.assertNotIn("chore(release)", git("log", "--all", "--format=%s", cwd=self.work).stdout)

    def test_nothing_under_unreleased(self):
        empty = PENDING.replace("### Added\n\n- A\n\n", "")
        self.stage(changelog=empty)
        outputs, done = self.prepare()
        self.assert_nothing_was_cut(outputs, done, "nothing is under [Unreleased]")
        self.assertEqual((self.work / "CHANGELOG.md").read_text(encoding="utf-8"), empty,
                         "refused before the file is rewritten")


if __name__ == "__main__":
    unittest.main()
