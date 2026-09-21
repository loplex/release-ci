#!/usr/bin/env python3
"""What merge-back does to a repository, exercised against one built for the purpose.

A bare repository stands in for the remote, so that pushing is a real push and a refused fast-forward is a
real refusal - which is the branch worth testing, being the one that catches the race. `gh` is a stub on
PATH: what it would say to GitHub is recorded and asserted, and nothing is sent anywhere.

Run with `python3 -m unittest discover` over the directory this file sits in.
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

MERGE_BACK = Path(__file__).resolve().parent / "merge-back" / "merge-back.sh"

AT_START = "# Changelog\n\n## [Unreleased]\n"
RELEASED = "# Changelog\n\n## [Unreleased]\n\n## [0.1.0] - 2026-09-21\n\n### Added\n\n- A\n"


def git(*arguments, cwd, check=True):
    return subprocess.run(["git", *arguments], cwd=cwd, check=check, capture_output=True, text=True)


class Staged(unittest.TestCase):
    """A repository in the state a published release leaves behind: a release commit on a branch of its own,
    tagged and pushed, and a default branch that has not seen it. Holds no tests of its own."""

    def stage(self, tag_prefix="v", at_start=AT_START, released=RELEASED):
        self.tag = f"{tag_prefix}0.1.0"
        root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.origin = root / "origin.git"
        self.work = root / "work"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.origin)], check=True)
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.work)], check=True,
                       capture_output=True)
        for name, value in (("user.email", "t@t"), ("user.name", "t")):
            git("config", name, value, cwd=self.work)

        (self.work / "CHANGELOG.md").write_text(at_start, encoding="utf-8")
        (self.work / "gradle.properties").write_text(
            f"version = 0.1.0-SNAPSHOT\ntagPrefix = {tag_prefix}\n", encoding="utf-8")
        git("add", "-A", cwd=self.work)
        git("commit", "-qm", "base", cwd=self.work)
        git("push", "-q", "-u", "origin", "main", cwd=self.work)

        # The release commit, on a branch of its own, tagged - the state a published release leaves behind.
        git("switch", "-qc", "release/0.1.0", cwd=self.work)
        (self.work / "gradle.properties").write_text(
            f"version = 0.1.0\ntagPrefix = {tag_prefix}\n", encoding="utf-8")
        (self.work / "CHANGELOG.md").write_text(released, encoding="utf-8")
        git("commit", "-qam", "chore(release): 0.1.0", cwd=self.work)
        git("tag", self.tag, cwd=self.work)
        git("push", "-q", "origin", "release/0.1.0", self.tag, cwd=self.work)

        self.said = root / "gh-said.txt"
        stubs = root / "bin"
        stubs.mkdir()
        (stubs / "gh").write_text(f'#!/bin/bash\nprintf "%s\\n" "$*" >> {self.said}\n', encoding="utf-8")
        (stubs / "gh").chmod(0o755)
        self.stubs = stubs

    def elsewhere(self, message):
        """Someone else landing on the default branch, from a clone of their own."""
        theirs = Path(self.enterContext(tempfile.TemporaryDirectory())) / "theirs"
        subprocess.run(["git", "clone", "-q", "--branch", "main", str(self.origin), str(theirs)],
                       check=True, capture_output=True)
        git("-c", "user.email=o", "-c", "user.name=o", "commit", "-q", "--allow-empty", "-m", message,
            cwd=theirs)
        git("push", "-q", "origin", "main", cwd=theirs)

    def carry_back(self, source="gradle.properties", tag_prefix="", fetch=True):
        # Not fetching is how the race is staged: the checkout knows the default branch as it stood when it
        # was made, which is exactly what a run holds while someone else pushes.
        if fetch:
            git("fetch", "-q", "origin", cwd=self.work)
        written = Path(self.enterContext(tempfile.TemporaryDirectory())) / "output.txt"
        written.write_text("", encoding="utf-8")
        done = subprocess.run(
            ["bash", str(MERGE_BACK)], cwd=self.work, capture_output=True, text=True,
            env={**os.environ, "PATH": f"{self.stubs}:{os.environ['PATH']}",
                 "SOURCE": source, "TAG": self.tag, "TAG_PREFIX": tag_prefix, "DEFAULT_BRANCH": "main",
                 "BRANCH_PREFIX": "release/", "BUILD_WORKFLOW": "build.yml",
                 "GITHUB_OUTPUT": str(written), "GH_TOKEN": "stub"},
        )
        outputs = dict(
            line.split("=", 1) for line in written.read_text(encoding="utf-8").splitlines() if "=" in line
        )
        return outputs, done

    def on_default_branch(self, reference):
        return git("merge-base", "--is-ancestor", reference, "main",
                   cwd=self.origin, check=False).returncode == 0

    def gh_said(self):
        return self.said.read_text(encoding="utf-8") if self.said.exists() else ""


class MergeBack(Staged):
    """The ways a release is carried back, and the ones that leave it to a pull request instead."""

    def setUp(self):
        self.stage()

    def test_a_release_lands_and_the_tag_goes_with_it(self):
        outputs, done = self.carry_back()
        self.assertEqual(outputs.get("landed"), "true", done.stderr)
        self.assertEqual(outputs.get("version"), "0.1.0")
        self.assertEqual(outputs.get("next"), "0.1.1-SNAPSHOT")
        self.assertTrue(self.on_default_branch(self.tag), "the tag has to be reachable from the branch")

    def test_the_next_version_is_opened_on_the_way(self):
        self.carry_back()
        declared = git("show", "main:gradle.properties", cwd=self.origin).stdout
        self.assertIn("version = 0.1.1-SNAPSHOT", declared)

    def test_a_build_is_asked_for_and_the_branch_taken_down(self):
        """A push made with GITHUB_TOKEN starts no run, so the branch would otherwise arrive unchecked."""
        self.carry_back()
        self.assertIn("workflow run build.yml --ref main", self.gh_said())
        self.assertNotIn("release/0.1.0", git("branch", "-a", cwd=self.origin).stdout)

    def test_work_that_landed_while_the_draft_waited_is_taken_in(self):
        self.elsewhere("landed while the draft waited")
        outputs, done = self.carry_back()
        self.assertEqual(outputs.get("landed"), "true", done.stderr)
        self.assertTrue(self.on_default_branch(self.tag))
        self.assertIn("landed while the draft waited",
                      git("log", "--format=%s", "main", cwd=self.origin).stdout)

    def test_a_default_branch_that_moves_under_the_push_is_not_pushed_past(self):
        """The race the unforced push exists to catch. Landing anyway would need --force, and would throw
        away whatever arrived in between."""
        self.elsewhere("won the race")
        # Run without fetching: the branch merges the default branch as this checkout knows it, and the push
        # then meets a remote that has moved. Fetching first would make the race disappear, and the test would
        # then pass while proving nothing.
        outputs, done = self.carry_back(fetch=False)
        self.assertEqual(outputs.get("landed"), "false", done.stdout + done.stderr)
        self.assertFalse(self.on_default_branch(self.tag))
        self.assertIn("pr create", self.gh_said())

    def test_a_conflict_is_left_to_the_pull_request(self):
        theirs = Path(self.enterContext(tempfile.TemporaryDirectory())) / "theirs"
        subprocess.run(["git", "clone", "-q", "--branch", "main", str(self.origin), str(theirs)],
                       check=True, capture_output=True)
        (theirs / "CHANGELOG.md").write_text(AT_START.replace("## [Unreleased]", "## [Unreleased]\n\n- theirs"),
                                             encoding="utf-8")
        git("-c", "user.email=o", "-c", "user.name=o", "commit", "-qam", "theirs", cwd=theirs)
        git("push", "-q", "origin", "main", cwd=theirs)

        git("switch", "-q", "release/0.1.0", cwd=self.work)
        (self.work / "CHANGELOG.md").write_text(RELEASED.replace("## [Unreleased]", "## [Unreleased]\n\n- ours"),
                                                encoding="utf-8")
        git("commit", "-qam", "ours", cwd=self.work)

        outputs, done = self.carry_back()
        self.assertEqual(outputs.get("landed"), "false", done.stdout + done.stderr)
        self.assertFalse(self.on_default_branch(self.tag))
        self.assertIn("pr create", self.gh_said())
        said = done.stdout + done.stderr
        self.assertIn("did not merge", said)
        # Told apart from the race above: reporting a conflict as merged would reach the push, be refused
        # for a different reason, and send the reader looking for a race that never happened.
        self.assertNotIn("moved while this ran", said)

    def test_a_source_recording_no_version_lands_all_the_same(self):
        """A repository versioned by its tags has nothing to write back, which is not a failure to write."""
        outputs, done = self.carry_back(source="tags", tag_prefix="v")
        self.assertEqual(outputs.get("landed"), "true", done.stdout + done.stderr)
        self.assertIn("records no version", done.stdout)

    def test_a_version_that_cannot_be_written_stops_the_run_before_anything_lands(self):
        """Only a source recording no version is let through. A write that failed read the same way would
        land the release with its own version still declared."""
        git("switch", "-q", "release/0.1.0", cwd=self.work)
        (self.work / "gradle.properties").write_text("version = 0.1.0\nversion = 0.1.0\ntagPrefix = v\n",
                                                     encoding="utf-8")
        git("commit", "-qam", "declared twice", cwd=self.work)
        outputs, done = self.carry_back()
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("could not be given 0.1.1-SNAPSHOT", done.stdout)
        self.assertNotIn("landed", outputs)
        self.assertFalse(self.on_default_branch(self.tag))


class WhereAMergeRewritesTheReleasedSection(Staged):
    """An entry added under [Unreleased] on the default branch while the draft waited. The release moved the
    lines above it into a section of its own, and a three-way merge, which sees lines rather than headings,
    puts the new entry into that released section - cleanly, without a conflict to stop it."""

    PREFIX = "v"

    def setUp(self):
        self.stage(tag_prefix=self.PREFIX, at_start="# Changelog\n\n## [Unreleased]\n\n### Added\n\n- A\n",
                   released="# Changelog\n\n## [Unreleased]\n\n## [0.1.0] - 2026-09-21\n\n### Added\n\n- A\n")
        theirs = Path(self.enterContext(tempfile.TemporaryDirectory())) / "theirs"
        subprocess.run(["git", "clone", "-q", "--branch", "main", str(self.origin), str(theirs)],
                       check=True, capture_output=True)
        (theirs / "CHANGELOG.md").write_text("# Changelog\n\n## [Unreleased]\n\n### Added\n\n- A\n- B\n",
                                             encoding="utf-8")
        git("-c", "user.email=o", "-c", "user.name=o", "commit", "-qam", "B", cwd=theirs)
        git("push", "-q", "origin", "main", cwd=theirs)

    def test_a_merged_tree_the_rules_refuse_is_not_pushed(self):
        outputs, done = self.carry_back()
        said = done.stdout + done.stderr
        self.assertEqual(outputs.get("landed"), "false", said)
        self.assertIn("changelog refused the result", said)
        self.assertFalse(self.on_default_branch(self.tag))
        self.assertIn("pr create", self.gh_said())

    def test_the_branch_offered_is_the_one_from_before_the_merge(self):
        """The pull request is where the entry is put back under [Unreleased], so it starts from the release
        as published, not from the merge that moved the entry."""
        self.carry_back()
        offered = git("show", "release/0.1.0:CHANGELOG.md", cwd=self.origin).stdout
        self.assertNotIn("- B", offered)


class WhereTagsCarryNoPrefix(WhereAMergeRewritesTheReleasedSection):
    """`^none` says the tags are bare. Handed on as a prefix of its own it would count no release, and the
    rules asked of the merged tree would pass having compared nothing."""

    PREFIX = ""

    def carry_back(self, source="tags", tag_prefix="^none", fetch=True):
        return super().carry_back(source=source, tag_prefix=tag_prefix, fetch=fetch)


class WhereTagsAreNamedDifferently(Staged):
    """The prefix is read from the source, not assumed. A repository tagging `release-0.1.0` and read as
    tagging `v*` keeps the whole tag as the version, which is no version, and stops before anything is
    carried back."""

    def setUp(self):
        self.stage("release-")

    def test_only_the_declared_prefix_comes_off_the_tag(self):
        outputs, done = self.carry_back()
        self.assertEqual(outputs.get("version"), "0.1.0", done.stdout + done.stderr)
        self.assertEqual(outputs.get("landed"), "true")
        self.assertTrue(self.on_default_branch(self.tag))


if __name__ == "__main__":
    unittest.main()
