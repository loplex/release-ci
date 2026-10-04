#!/usr/bin/env python3
"""What prepare does to a repository, tested against one built for the purpose.

A bare repository stands in for the remote, so a test can see that nothing reaches it.
prepare pushes nothing: the build runs from its commit next.
Nothing here needs `gh`: prepare stops before anything is drafted.

Run with `python3 -m unittest discover -s release-flow` from the repository root.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PREPARE = Path(__file__).resolve().parent.parent / "prepare" / "prepare.sh"

PENDING = "# Changelog\n\n## [Unreleased]\n\n### Fixed\n\n- F\n\n## [0.1.0] - 2026-09-01\n\n- old\n"


def git(*arguments, cwd, check=True):
    return subprocess.run(["git", *arguments], cwd=cwd, check=check, capture_output=True, text=True)


class Staged(unittest.TestCase):
    """A repository between releases.

    0.1.0 is tagged and work is under [Unreleased].
    Where the source declares a version, the next one is declared with its marker.
    """

    def stage(self, properties="version = 0.1.1-SNAPSHOT\ntagPrefix = v\n", changelog=PENDING, tag="v0.1.0"):
        root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.origin = root / "origin.git"
        self.work = root / "work"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.origin)], check=True)
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.work)], check=True,
                       capture_output=True)
        for name, value in (("user.email", "t@t"), ("user.name", "t")):
            git("config", name, value, cwd=self.work)
        (self.work / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
        if properties is not None:
            (self.work / "gradle.properties").write_text(properties, encoding="utf-8")
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
            env={**os.environ, "PYTHON": sys.executable, "VERSION_SOURCE": source, "TAG_PREFIX": tag_prefix,
                 "VERSION": version, "REPOSITORY_URL": repository_url, "GITHUB_OUTPUT": str(written)},
        )
        outputs = dict(
            line.split("=", 1) for line in written.read_text(encoding="utf-8").splitlines() if "=" in line
        )
        return outputs, done

    def file_on(self, branch, name):
        return git("show", f"{branch}:{name}", cwd=self.work).stdout

    def release_branches(self):
        return git("for-each-ref", "--format=%(refname:short)", "refs/heads/release", cwd=self.work).stdout.split()


class Prepare(Staged):
    def test_the_release_commit_is_cut_onto_a_branch_of_its_own(self):
        outputs, done = self.prepare()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(outputs, {"version": "0.1.1", "tag": "v0.1.1", "branch": "release/0.1.1"})
        self.assertEqual(git("branch", "--show-current", cwd=self.work).stdout.strip(), "release/0.1.1",
                         "the build runs from the release commit next, so the workspace is left on it")
        self.assertIn("chore(release): 0.1.1", git("log", "-1", "--format=%s", cwd=self.work).stdout)
        self.assertEqual(git("branch", "--contains", "HEAD", cwd=self.work).stdout, "* release/0.1.1\n",
                         "no other branch holds the release commit")

    def test_nothing_reaches_the_remote(self):
        """A build that fails after this should leave neither a branch nor a draft, so pushing waits for it.

        Every ref the remote has is compared, not only the release branch.
        A tag or another branch pushed early would be on the remote just as much.
        """
        before = git("for-each-ref", cwd=self.origin).stdout
        _, done = self.prepare()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(git("for-each-ref", cwd=self.origin).stdout, before)

    def test_the_link_definitions_are_written_where_a_repository_url_is_given(self):
        self.prepare(repository_url="https://example.invalid/r")
        changelog = self.file_on("release/0.1.1", "CHANGELOG.md")
        self.assertIn("[0.1.1]: https://example.invalid/r/compare/v0.1.0...v0.1.1\n", changelog)

    def test_the_marker_comes_off_the_declared_version(self):
        self.prepare()
        self.assertIn("version = 0.1.1\n", self.file_on("release/0.1.1", "gradle.properties"))

    def test_a_version_handed_in_without_the_marker_is_released_as_it_is(self):
        """Only a marker at the end of the version comes off, and 0.2.0 has none.

        The version differs from the declared 0.1.1, so a version handed in and then ignored would show.
        """
        outputs, done = self.prepare(version="0.2.0")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(outputs["version"], "0.2.0")
        self.assertIn("version = 0.2.0\n", self.file_on("release/0.2.0", "gradle.properties"))

    def test_the_pending_entries_become_the_released_section(self):
        self.prepare()
        changelog = self.file_on("release/0.1.1", "CHANGELOG.md")
        self.assertIn("## [0.1.1] - ", changelog)
        self.assertIn("### Fixed\n\n- F\n", changelog)
        self.assertRegex(changelog, r"## \[Unreleased\]\n\n## \[0\.1\.1\]")  # Nothing is left pending.

    def test_the_default_branch_is_not_touched(self):
        """The local default branch, the one prepare can reach.

        test_nothing_reaches_the_remote covers the remote's.
        A release commit made on the local one too would go out with its next push.
        """
        before = git("rev-parse", "main", cwd=self.work).stdout
        _, done = self.prepare()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(git("rev-parse", "main", cwd=self.work).stdout, before)

    def test_a_source_declaring_no_version_releases_what_it_is_handed(self):
        self.stage(properties=None)
        outputs, done = self.prepare(source="tags", tag_prefix="v", version="0.2.0")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(outputs["tag"], "v0.2.0")
        self.assertIn("declares no version, so none was written; v0.2.0 is what the tag will say", done.stdout)
        self.assertIn("## [0.2.0] - ", self.file_on("release/0.2.0", "CHANGELOG.md"))

    def test_a_source_declaring_no_version_defaults_to_the_version_after_the_highest(self):
        """A patch, because the highest release, 0.10.0, is final and [Unreleased] holds only a fix.

        What follows an open pre-release train is tested beside `next_candidate` in check-release, not here.
        Lower releases sit beside it, and 0.9.0 sorts after it by name.
        So the highest is neither the only release nor the last one `git tag -l` lists.
        """
        self.stage(properties=None)
        for tag in ("v0.0.9", "v0.9.0", "v0.10.0"):
            git("tag", tag, cwd=self.work)
        outputs, done = self.prepare(source="tags", tag_prefix="v")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(outputs["version"], "0.10.1")

    def test_none_says_the_tags_carry_no_prefix(self):
        """Passed on as a literal prefix, `^none` would match no release.

        There would then be no release to count the default from.
        """
        self.stage(properties=None, tag="0.1.0")
        outputs, done = self.prepare(source="tags", tag_prefix="^none")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual((outputs["version"], outputs["tag"]), ("0.1.1", "0.1.1"))

    def test_a_second_attempt_at_the_same_version_starts_again(self):
        """A branch left by an earlier attempt is replaced, not continued.

        The release commit is then still the only commit on top of the default branch.
        The default branch moves between the two attempts.
        A branch continued with the new tree carried onto it would get a second commit, and the count would be 2.
        Continued any other way, the run fails at the switch or on an empty commit, and the return code shows it.
        """
        self.prepare()
        git("switch", "-q", "main", cwd=self.work)
        (self.work / "more.txt").write_text("landed meanwhile\n", encoding="utf-8")
        git("add", "more.txt", cwd=self.work)
        git("commit", "-qm", "more work", cwd=self.work)
        git("push", "-q", "origin", "main", cwd=self.work)
        outputs, done = self.prepare()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(git("rev-list", "--count", "main..release/0.1.1", cwd=self.work).stdout.strip(), "1")

    def test_a_version_that_cannot_be_written_leaves_its_branch_with_no_commit(self):
        """The version is declared twice, which the writer refuses.

        Treated like a source that declares nothing, the release commit would keep -SNAPSHOT on the line Gradle
        reads, and the build would make a snapshot.
        The branch is cut after the changelog is closed and before the version is written.
        So it is left with no commit on it, and the next attempt at the version replaces it.
        """
        self.stage(properties="version = 0.1.1-SNAPSHOT\nversion = 0.1.1-SNAPSHOT\ntagPrefix = v\n")
        outputs, done = self.prepare()
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertEqual(outputs, {})
        self.assertIn("could not be given 0.1.1", done.stdout)
        self.assertIn("release/0.1.1", self.release_branches(), "the branch was cut before the write failed")
        self.assertNotIn("chore(release)", git("log", "--all", "--format=%s", cwd=self.work).stdout)
        self.assertEqual(git("rev-list", "--count", "main..release/0.1.1", cwd=self.work).stdout.strip(), "0")


class NothingIsCutWhereTheRulesSayNo(Staged):
    """A release that fails the checks is never cut, so there is nothing to undo.

    No release branch, no output, nothing written, and the workspace still on the default branch.
    """

    def assert_nothing_was_cut(self, outputs, done, saying):
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(outputs, {})
        self.assertIn(saying, done.stdout + done.stderr)
        self.assertEqual(self.release_branches(), [], "no release branch is cut where the rules say no")
        self.assertEqual(git("branch", "--show-current", cwd=self.work).stdout.strip(), "main")
        self.assertEqual(git("status", "--porcelain", cwd=self.work).stdout, "",
                         "nothing is written where the rules say no")
        self.assertEqual(git("rev-list", "--count", "origin/main..main", cwd=self.work).stdout.strip(), "0",
                         "nothing is committed where the rules say no")

    def test_a_version_the_step_refuses(self):
        outputs, done = self.prepare(version="0.4.0-SNAPSHOT")
        self.assert_nothing_was_cut(outputs, done, "does not follow 0.1.0")

    def test_a_patch_over_an_addition(self):
        self.stage(changelog=PENDING.replace("### Fixed\n\n- F\n", "### Added\n\n- A\n"))
        outputs, done = self.prepare()
        self.assert_nothing_was_cut(outputs, done, "[Unreleased] holds ### Added")

    def test_a_released_section_that_was_edited(self):
        (self.work / "CHANGELOG.md").write_text(PENDING.replace("- old", "- old, said better"), encoding="utf-8")
        git("commit", "-qam", "edit", cwd=self.work)
        git("push", "-q", "origin", "main", cwd=self.work)
        outputs, done = self.prepare()
        self.assert_nothing_was_cut(outputs, done, "no longer reads as the tag has it")

    def test_nothing_under_unreleased(self):
        nothing_pending = PENDING.replace("### Fixed\n\n- F\n\n", "")
        self.stage(changelog=nothing_pending)
        outputs, done = self.prepare()
        self.assert_nothing_was_cut(outputs, done, "nothing is under [Unreleased]")
        self.assertEqual((self.work / "CHANGELOG.md").read_text(encoding="utf-8"), nothing_pending,
                         "refused before the file is rewritten")


if __name__ == "__main__":
    unittest.main()
