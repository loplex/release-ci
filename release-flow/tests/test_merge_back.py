#!/usr/bin/env python3
"""What merge-back does to a repository, tested against one built for the purpose.

A bare repository stands in for the remote, so a push is a real push and a refused fast-forward a real refusal.
That refusal is the path most worth testing, because it is the one that catches the race.
`gh` is a stub on PATH: what it would send to GitHub is recorded and asserted, and nothing is sent anywhere.

Run with `python3 -m unittest discover -s release-flow` from the repository root.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

MERGE_BACK = Path(__file__).resolve().parent.parent / "merge-back" / "merge-back.sh"

AT_START = "# Changelog\n\n## [Unreleased]\n"
RELEASED = "# Changelog\n\n## [Unreleased]\n\n## [0.1.0] - 2026-09-21\n\n### Added\n\n- A\n"


def git(*arguments, cwd, check=True):
    return subprocess.run(["git", *arguments], cwd=cwd, check=check, capture_output=True, text=True)


class Staged(unittest.TestCase):
    """A repository in the state a published release leaves behind.

    A release commit on a branch of its own, tagged and pushed, and a default branch that does not have it yet.
    This class holds no tests of its own.
    """

    def stage(self, prefix="v", at_start=AT_START, released=RELEASED):
        self.tag = f"{prefix}0.1.0"
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
            f"version = 0.1.0-SNAPSHOT\ntagPrefix = {prefix}\n", encoding="utf-8")
        git("add", "-A", cwd=self.work)
        git("commit", "-qm", "base", cwd=self.work)
        git("push", "-q", "-u", "origin", "main", cwd=self.work)

        # The release commit, on a branch of its own and tagged: the state a published release leaves behind.
        git("switch", "-qc", "release/0.1.0", cwd=self.work)
        (self.work / "gradle.properties").write_text(
            f"version = 0.1.0\ntagPrefix = {prefix}\n", encoding="utf-8")
        (self.work / "CHANGELOG.md").write_text(released, encoding="utf-8")
        git("commit", "-qam", "chore(release): 0.1.0", cwd=self.work)
        git("tag", self.tag, cwd=self.work)
        git("push", "-q", "origin", "release/0.1.0", self.tag, cwd=self.work)

        self.gh_log = root / "gh-said.txt"
        stubs = root / "bin"
        stubs.mkdir()
        (stubs / "gh").write_text(f'#!/bin/bash\nprintf "%s\\n" "$*" >> {self.gh_log}\n', encoding="utf-8")
        (stubs / "gh").chmod(0o755)
        self.stubs = stubs

    def land_elsewhere(self, message, files=None):
        """Someone else pushing to the default branch from a clone of their own.

        `files` maps names to text; without it the commit is empty, for where only its place in the history matters.
        """
        theirs = Path(self.enterContext(tempfile.TemporaryDirectory())) / "theirs"
        subprocess.run(["git", "clone", "-q", "--branch", "main", str(self.origin), str(theirs)],
                       check=True, capture_output=True)
        for name, text in (files or {}).items():
            (theirs / name).write_text(text, encoding="utf-8")
            git("add", name, cwd=theirs)
        git("-c", "user.email=o", "-c", "user.name=o", "commit", "-q", "--allow-empty", "-m", message,
            cwd=theirs)
        git("push", "-q", "origin", "main", cwd=theirs)

    def carry_back(self, source="gradle.properties", tag_prefix="", fetch=True, check_workflow="ci.yml",
                   skip_unreadable_releases="false"):
        # Not fetching is how the race is staged.
        # The checkout knows the default branch as it was when the checkout was made, as a run does while someone
        # else pushes.
        if fetch:
            git("fetch", "-q", "origin", cwd=self.work)
        written = Path(self.enterContext(tempfile.TemporaryDirectory())) / "output.txt"
        written.write_text("", encoding="utf-8")
        done = subprocess.run(
            ["bash", str(MERGE_BACK)], cwd=self.work, capture_output=True, text=True,
            env={**os.environ, "PYTHON": sys.executable, "PATH": f"{self.stubs}:{os.environ['PATH']}",
                 "VERSION_SOURCE": source, "TAG": self.tag, "TAG_PREFIX": tag_prefix, "DEFAULT_BRANCH": "main",
                 "CHECK_WORKFLOW": check_workflow, "SKIP_UNREADABLE_RELEASES": skip_unreadable_releases,
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
        return self.gh_log.read_text(encoding="utf-8") if self.gh_log.exists() else ""


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
        self.assertNotIn("::notice::", done.stdout, "nothing was merged in, so nothing is said of it")

    def test_a_tag_holding_a_line_not_read_leaves_the_merge_to_a_pull_request_unless_skipped(self):
        """v0.0.9's copy of CHANGELOG.md holds a block quote, and a tag cannot be edited.
        It stands above the section, so the section's absence from the tree, skipped, is no deletion.
        The option goes to `changelog` alone: `ancestry` would refuse it, and the release would not land."""
        git("switch", "-q", "main", cwd=self.work)
        tagged = AT_START + "\n> q\n\n## [0.0.9] - 2026-01-01\n\n- q\n"
        (self.work / "CHANGELOG.md").write_text(tagged, encoding="utf-8")
        git("commit", "-qam", "0.0.9", cwd=self.work)
        git("tag", "v0.0.9", cwd=self.work)
        (self.work / "CHANGELOG.md").write_text(AT_START, encoding="utf-8")
        git("commit", "-qam", "back", cwd=self.work)
        git("push", "-q", "origin", "main", "v0.0.9", cwd=self.work)
        git("switch", "-q", "release/0.1.0", cwd=self.work)
        outputs, done = self.carry_back()
        self.assertEqual(outputs.get("landed"), "false", done.stdout + done.stderr)
        self.assertIn("holds a block quote", done.stderr)
        outputs, done = self.carry_back(skip_unreadable_releases="true")
        self.assertEqual(outputs.get("landed"), "true", done.stdout + done.stderr)

    def test_skip_unreadable_releases_is_true_or_false(self):
        outputs, done = self.carry_back(skip_unreadable_releases="yes")
        self.assertEqual(done.returncode, 1)
        self.assertIn("skip-unreadable-releases is 'yes', which is neither true nor false", done.stdout)
        self.assertEqual(outputs, {})

    def test_the_next_version_is_opened_on_the_way(self):
        self.carry_back()
        properties = git("show", "main:gradle.properties", cwd=self.origin).stdout
        self.assertIn("version = 0.1.1-SNAPSHOT", properties)

    def test_a_check_is_asked_for_and_the_branch_taken_down(self):
        """A push made with GITHUB_TOKEN starts no run, so the branch would otherwise arrive unchecked.

        The check is started once the release is on the branch.
        Started before, it would check the default branch as it was.
        """
        asked_of = self.gh_log.with_name("asked-of.txt")
        gh = (self.stubs / "gh").read_text(encoding="utf-8")
        (self.stubs / "gh").write_text(
            gh + f'[[ "$1 $2" == "workflow run" ]] && git -C {self.origin} rev-parse main >> {asked_of}\nexit 0\n',
            encoding="utf-8")
        self.carry_back()
        self.assertIn("workflow run ci.yml --ref main", self.gh_said())
        self.assertEqual(asked_of.read_text(encoding="utf-8") if asked_of.exists() else "",
                         git("rev-parse", "main", cwd=self.origin).stdout,
                         "the check is asked of the default branch the release has landed on")
        self.assertNotIn("release/0.1.0", git("branch", "-a", cwd=self.origin).stdout)

    def test_a_check_that_cannot_be_asked_for_only_warns(self):
        """The release is out and on the default branch by then.

        A refused dispatch, from a token without `actions: write`, only warns, and the branch is still deleted.
        """
        gh = (self.stubs / "gh").read_text(encoding="utf-8")
        (self.stubs / "gh").write_text(gh + '[[ "$1 $2" == "workflow run" ]] && exit 1\nexit 0\n', encoding="utf-8")
        outputs, done = self.carry_back()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(outputs.get("landed"), "true")
        self.assertIn("::warning::ci.yml was not started for main; start it by hand", done.stdout)
        self.assertNotIn("release/0.1.0", git("branch", "-a", cwd=self.origin).stdout)

    def test_a_branch_that_cannot_be_taken_down_only_warns(self):
        """Deleting the branch is cleanup after a release that has landed: a refusal warns, it does not fail."""
        hook = self.origin / "hooks" / "pre-receive"
        hook.write_text('#!/bin/bash\nwhile read -r old new ref; do\n'
                        '  [[ $ref == refs/heads/release/0.1.0 && $new =~ ^0+$ ]] && exit 1\n'
                        'done\nexit 0\n', encoding="utf-8")
        hook.chmod(0o755)
        outputs, done = self.carry_back()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(outputs.get("landed"), "true")
        self.assertIn("::warning::release/0.1.0 is still there; it has landed and can be deleted", done.stdout)
        self.assertIn("release/0.1.0", git("branch", "-a", cwd=self.origin).stdout)

    def test_a_check_workflow_left_out_is_refused_before_anything_lands(self):
        """GitHub does not enforce `required`: an input left out arrives empty.

        Skipping the check would land a release with nothing started to check it.
        """
        outputs, done = self.carry_back(check_workflow="")
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("check-workflow names no workflow", done.stdout)
        self.assertEqual(outputs, {})
        self.assertFalse(self.on_default_branch(self.tag))

    def test_work_that_landed_since_the_release_was_cut_is_taken_in(self):
        """The other work is taken in whole, not only as history.

        A merge that kept the commit but dropped its changes would put its subject on the default branch and the
        work nowhere.
        """
        self.land_elsewhere("landed since the release was cut", {"work.txt": "landed\n"})
        outputs, done = self.carry_back()
        self.assertEqual(outputs.get("landed"), "true", done.stderr)
        self.assertTrue(self.on_default_branch(self.tag))
        self.assertIn("landed since the release was cut",
                      git("log", "--format=%s", "main", cwd=self.origin).stdout)
        self.assertEqual(git("show", "main:work.txt", cwd=self.origin, check=False).stdout, "landed\n")
        self.assertIn(f"::notice::main moved while {self.tag} was out: 1 commit(s) that landed meanwhile were merged "
                      "in by 1 merge commit(s)", done.stdout)

    def test_a_merge_the_default_branch_took_in_meanwhile_is_not_counted_as_the_landing_s(self):
        theirs = Path(self.enterContext(tempfile.TemporaryDirectory())) / "theirs"
        subprocess.run(["git", "clone", "-q", "--branch", "main", str(self.origin), str(theirs)],
                       check=True, capture_output=True)
        identity = ["-c", "user.email=o", "-c", "user.name=o"]
        git("switch", "-qc", "feature", cwd=theirs)
        (theirs / "feature.txt").write_text("f\n", encoding="utf-8")
        git("add", "feature.txt", cwd=theirs)
        git(*identity, "commit", "-qm", "feature", cwd=theirs)
        git("switch", "-q", "main", cwd=theirs)
        git(*identity, "merge", "-q", "--no-ff", "-m", "Merge pull request #1", "feature", cwd=theirs)
        git("push", "-q", "origin", "main", cwd=theirs)
        outputs, done = self.carry_back()
        self.assertEqual(outputs.get("landed"), "true", done.stdout + done.stderr)
        self.assertIn(f"::notice::main moved while {self.tag} was out: 2 commit(s) that landed meanwhile were merged "
                      "in by 1 merge commit(s)", done.stdout)

    def test_a_repeated_run_that_lands_an_earlier_run_s_merge_says_so(self):
        """The first run merges, and its push is refused; the second finds the merge already on the branch."""
        self.land_elsewhere("landed since the release was cut", {"work.txt": "landed\n"})
        hook = self.origin / "hooks" / "pre-receive"
        hook.write_text('#!/bin/bash\ngrep -q " refs/heads/main$" && exit 1\nexit 0\n', encoding="utf-8")
        hook.chmod(0o755)
        outputs, first = self.carry_back()
        self.assertEqual(outputs.get("landed"), "false", first.stdout + first.stderr)
        self.assertNotIn("::notice::", first.stdout, "nothing landed, so no merge landed with it")
        hook.unlink()
        # A fresh checkout, as a repeated run makes: the tag, and the branch only as the remote has it.
        git("switch", "-q", "--detach", self.tag, cwd=self.work)
        git("branch", "-q", "-D", "release/0.1.0", cwd=self.work)
        outputs, done = self.carry_back()
        self.assertEqual(outputs.get("landed"), "true", done.stdout + done.stderr)
        self.assertIn(f"::notice::main moved while {self.tag} was out: 1 commit(s) that landed meanwhile were merged "
                      "in by 1 merge commit(s)", done.stdout)

    def test_a_repeated_run_that_finds_more_landed_merges_again_and_counts_both(self):
        """The earlier run's merge, and this run's of what landed since: two merges, two commits taken in."""
        self.land_elsewhere("landed first", {"one.txt": "1\n"})
        hook = self.origin / "hooks" / "pre-receive"
        hook.write_text('#!/bin/bash\ngrep -q " refs/heads/main$" && exit 1\nexit 0\n', encoding="utf-8")
        hook.chmod(0o755)
        outputs, first = self.carry_back()
        self.assertEqual(outputs.get("landed"), "false", first.stdout + first.stderr)
        hook.unlink()
        self.land_elsewhere("landed second", {"two.txt": "2\n"})
        git("switch", "-q", "--detach", self.tag, cwd=self.work)
        git("branch", "-q", "-D", "release/0.1.0", cwd=self.work)
        outputs, done = self.carry_back()
        self.assertEqual(outputs.get("landed"), "true", done.stdout + done.stderr)
        self.assertIn(f"::notice::main moved while {self.tag} was out: 2 commit(s) that landed meanwhile were merged "
                      "in by 2 merge commit(s)", done.stdout)

    def test_a_default_branch_that_moves_under_the_push_is_not_pushed_past(self):
        """The race the unforced push exists to catch.

        Landing anyway would need --force, and would throw away whatever arrived in between.
        """
        self.land_elsewhere("won the race")
        # Run without fetching: the branch merges the default branch as this checkout knows it.
        # The push then meets a remote that has moved.
        # Fetching first would remove the race: the push would land, and the test would assert a race it never staged.
        outputs, done = self.carry_back(fetch=False)
        self.assertEqual(outputs.get("landed"), "false", done.stdout + done.stderr)
        self.assertFalse(self.on_default_branch(self.tag))
        self.assertIn("pr create", self.gh_said())
        self.assertIn("Until this is merged, `main` does not reach `v0.1.0`", self.gh_said())
        self.assertIn("`changelog` warn of it", self.gh_said())
        self.assertIn("Delete `release/0.1.0` once this is merged", self.gh_said())

    def test_a_default_branch_that_takes_no_push_is_left_to_the_pull_request(self):
        """A protected default branch refuses the push every time.

        The warning cannot tell that from the race, so it names both.
        """
        hook = self.origin / "hooks" / "pre-receive"
        hook.write_text('#!/bin/bash\ngrep -q " refs/heads/main$" && exit 1\nexit 0\n', encoding="utf-8")
        hook.chmod(0o755)
        outputs, done = self.carry_back()
        self.assertEqual(outputs.get("landed"), "false", done.stdout + done.stderr)
        self.assertIn("::warning::the push to main was refused: it moved while this ran, or it takes no push "
                      "from the credential the checkout left", done.stdout)
        self.assertFalse(self.on_default_branch(self.tag))
        self.assertIn("pr create --base main --head release/0.1.0 ", self.gh_said())

    def test_a_merged_tree_with_another_release_yet_to_land_is_left_to_the_pull_request(self):
        """0.0.9 is published from a branch of its own too, and has yet to land.
        The checks of the merged tree exit with 4 for it, which merge-back takes as it takes any other refusal."""
        git("switch", "-qc", "release/0.0.9", "origin/main", cwd=self.work)
        (self.work / "CHANGELOG.md").write_text("# Changelog\n\n## [Unreleased]\n\n## [0.0.9] - 2026-09-20\n\n- Z\n",
                                                encoding="utf-8")
        git("commit", "-qam", "chore(release): 0.0.9", cwd=self.work)
        git("tag", "v0.0.9", cwd=self.work)
        git("push", "-q", "origin", "release/0.0.9", "v0.0.9", cwd=self.work)
        git("switch", "-q", "release/0.1.0", cwd=self.work)
        outputs, done = self.carry_back()
        printed = done.stdout + done.stderr
        self.assertEqual(outputs.get("landed"), "false", printed)
        self.assertIn("refused the result", printed)
        self.assertIn("[0.0.9] is released, and has yet to land here", printed)
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
        self.assertIn("pr create --base main --head release/0.1.0 ", self.gh_said())
        printed = done.stdout + done.stderr
        self.assertIn("did not merge", printed)
        on_branch = git("log", "--format=%s", f"{self.tag}..release/0.1.0", cwd=self.origin).stdout.splitlines()
        self.assertEqual(on_branch, ["chore: start 0.1.1-SNAPSHOT", "ours"], "the branch as it was before the merge")
        # Told apart from the race above.
        # A conflict reported as merged would reach the push and be refused for a different reason.
        # The reader would then look for a race that never happened.
        self.assertNotIn("moved while this ran", printed)

    def test_a_source_declaring_no_version_lands_all_the_same(self):
        """A repository versioned by its tags has nothing to write back, and that is not a failed write."""
        outputs, done = self.carry_back(source="tags", tag_prefix="v")
        self.assertEqual(outputs.get("landed"), "true", done.stdout + done.stderr)
        self.assertTrue(self.on_default_branch(self.tag), "the tag has to be reachable from the branch")
        self.assertIn("records no version", done.stdout)

    def test_a_pull_request_names_the_version_it_opened(self):
        """The body also says that a feature that landed while the release was out asks for more than that version.

        A version check refusing it here is then not read as the release's fault.
        """
        self.land_elsewhere("won the race")
        self.carry_back(fetch=False)
        self.assertIn("--title Release 0.1.0, and start 0.1.1-SNAPSHOT --body", self.gh_said())
        self.assertIn("This branch starts `0.1.1-SNAPSHOT`, counted from `0.1.0` alone.", self.gh_said())
        self.assertIn("followed by the marker `0.1.1-SNAPSHOT` carries", self.gh_said())

    def test_a_pull_request_under_a_source_declaring_no_version_claims_none_opened(self):
        """Nothing was written back.

        A title saying the next version was started would name a commit the branch does not have.
        """
        self.land_elsewhere("won the race")
        self.carry_back(source="tags", tag_prefix="v", fetch=False)
        self.assertIn("--title Release 0.1.0 --body", self.gh_said())
        self.assertNotIn("This branch starts", self.gh_said())

    def test_a_release_branch_that_cannot_be_pushed_opens_no_pull_request(self):
        """Opened anyway, the pull request would carry the branch as the remote has it.

        That branch lacks the commit starting the next version, under a title saying it has one, and the step
        would pass.
        """
        self.land_elsewhere("won the race")
        hook = self.origin / "hooks" / "pre-receive"
        hook.write_text('#!/bin/bash\ngrep -q " refs/heads/release/" && exit 1\nexit 0\n', encoding="utf-8")
        hook.chmod(0o755)
        outputs, done = self.carry_back(fetch=False)
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("::error::release/0.1.0 could not be pushed", done.stdout)
        self.assertNotIn("pr create", self.gh_said())
        self.assertEqual(outputs.get("landed"), "false")

    def test_a_version_that_cannot_be_written_stops_the_run_before_anything_lands(self):
        """Only a source that declares no version is let through.

        A failed write treated the same way would land the release with its own version still declared.
        """
        git("switch", "-q", "release/0.1.0", cwd=self.work)
        (self.work / "gradle.properties").write_text("version = 0.1.0\nversion = 0.1.0\ntagPrefix = v\n",
                                                     encoding="utf-8")
        git("commit", "-qam", "declared twice", cwd=self.work)
        outputs, done = self.carry_back()
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("could not be given 0.1.1-SNAPSHOT", done.stdout)
        self.assertNotIn("landed", outputs)
        self.assertFalse(self.on_default_branch(self.tag))

    def test_a_run_repeated_after_its_pull_request_was_refused_carries_on(self):
        """The first run pushed the branch with the next version started on it, and was refused the pull request.

        Actions not being allowed to open one is such a case.
        The repeated run finds that commit on the branch and has nothing to write, which is no reason to fail.
        Its pull request still says the next version was started.
        """
        self.land_elsewhere("won the race")
        gh = (self.stubs / "gh").read_text(encoding="utf-8")
        (self.stubs / "gh").write_text(gh + '[[ "$1 $2" == "pr create" ]] && exit 1\nexit 0\n', encoding="utf-8")
        _, first = self.carry_back(fetch=False)
        self.assertNotEqual(first.returncode, 0, first.stdout + first.stderr)
        (self.stubs / "gh").write_text(gh, encoding="utf-8")
        # A fresh checkout, as a repeated run makes: the tag, and the branch only as the remote has it.
        git("switch", "-q", "--detach", self.tag, cwd=self.work)
        git("branch", "-q", "-D", "release/0.1.0", cwd=self.work)
        _, done = self.carry_back(fetch=False)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        create_calls = [line for line in self.gh_said().splitlines() if line.startswith("pr create")]
        self.assertEqual(len(create_calls), 2)
        self.assertIn("--title Release 0.1.0, and start 0.1.1-SNAPSHOT --body", create_calls[-1])
        on_branch = git("log", "--format=%s", "release/0.1.0", cwd=self.origin).stdout.splitlines()
        self.assertEqual(on_branch.count("chore: start 0.1.1-SNAPSHOT"), 1)

    def test_a_run_repeated_while_its_pull_request_is_open_and_the_push_still_refused_leaves_it_open(self):
        """Repeating the job is how a failed later step is retried.

        Where the release went to a pull request nobody has merged yet, that pull request is still there.
        Here the push is refused again: the race is staged a second time, by not fetching.
        GitHub would refuse a second pull request for the same branch.
        Failing on that would show a red run for a release carried back as before.
        """
        self.land_elsewhere("won the race")
        _, first = self.carry_back(fetch=False)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        said_before = self.gh_said().splitlines()
        url = "https://github.com/o/r/pull/1"
        gh = (self.stubs / "gh").read_text(encoding="utf-8")
        (self.stubs / "gh").write_text(gh + f'[[ "$1 $2" == "pr list" ]] && echo {url}\nexit 0\n', encoding="utf-8")
        # A fresh checkout, as a repeated run makes: the tag, and the branch only as the remote has it.
        git("switch", "-q", "--detach", self.tag, cwd=self.work)
        git("branch", "-q", "-D", "release/0.1.0", cwd=self.work)
        outputs, done = self.carry_back(fetch=False)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(outputs.get("landed"), "false")
        self.assertIn(f"{url} carries {self.tag} back already", done.stdout)
        create_calls = [line for line in self.gh_said().splitlines() if line.startswith("pr create")]
        self.assertEqual(len(create_calls), 1, "the pull request the first run opened is the one that carries it")
        asked = [line.split()[:2] for line in self.gh_said().splitlines()[len(said_before):] if line.startswith("pr ")]
        self.assertEqual(asked, [["pr", "list"]], "the open pull request is asked about, and left as it is")
        self.assertIn("pr list --base main --head release/0.1.0 --state open ", self.gh_said())

    def test_a_run_repeated_while_its_pull_request_is_open_lands_where_it_now_can(self):
        """The race is over by the time the job runs again.

        A fresh checkout sees the default branch as it is now.
        The release lands, and the branch the pull request carried is deleted.
        """
        self.land_elsewhere("won the race")
        _, first = self.carry_back(fetch=False)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        gh = (self.stubs / "gh").read_text(encoding="utf-8")
        (self.stubs / "gh").write_text(
            gh + '[[ "$1 $2" == "pr list" ]] && echo https://github.com/o/r/pull/1\nexit 0\n', encoding="utf-8")
        # A fresh checkout, as a repeated run makes: the tag, and the branch only as the remote has it.
        git("switch", "-q", "--detach", self.tag, cwd=self.work)
        git("branch", "-q", "-D", "release/0.1.0", cwd=self.work)
        outputs, done = self.carry_back()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(outputs.get("landed"), "true")
        self.assertTrue(self.on_default_branch(self.tag))
        self.assertNotIn("release/0.1.0", git("branch", "--list", cwd=self.origin).stdout)
        create_calls = [line for line in self.gh_said().splitlines() if line.startswith("pr create")]
        self.assertEqual(len(create_calls), 1, "no second pull request beside the one the first run opened")

    def test_a_run_repeated_after_the_release_landed_passes_and_pushes_nothing(self):
        """Repeating the job is how a failed later step is retried, and by then the release branch is deleted.

        The run finds the tag on the default branch and says the release has landed.
        """
        self.carry_back()
        refs_before = git("for-each-ref", cwd=self.origin).stdout
        # A fresh checkout, as a repeated run makes: the tag, and no release branch.
        git("switch", "-q", "--detach", self.tag, cwd=self.work)
        git("branch", "-q", "-D", "release/0.1.0", cwd=self.work)
        outputs, done = self.carry_back()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual((outputs.get("landed"), outputs.get("version")), ("true", "0.1.0"))
        self.assertIn("the release has landed", done.stdout)
        self.assertEqual(git("for-each-ref", cwd=self.origin).stdout, refs_before, "the remote is left as it was")
        self.assertEqual(self.gh_said().count("workflow run"), 1, "the check is asked for by the run that landed")


class WhereAMergeRewritesTheReleasedSection(Staged):
    """An entry added under [Unreleased] on the default branch since the release was cut.

    The release moved the lines above it into a section of its own.
    A three-way merge sees lines, not headings, so it puts the new entry into that released section.
    It does so cleanly, with no conflict to stop it.
    """

    PREFIX = "v"
    # What the run writes on the release branch before it tries the merge: the commit starting the next version.
    OPENED = ["chore: start 0.1.1-SNAPSHOT"]

    def setUp(self):
        self.stage(prefix=self.PREFIX, at_start="# Changelog\n\n## [Unreleased]\n\n### Added\n\n- A\n",
                   released="# Changelog\n\n## [Unreleased]\n\n## [0.1.0] - 2026-09-21\n\n### Added\n\n- A\n")
        theirs = Path(self.enterContext(tempfile.TemporaryDirectory())) / "theirs"
        subprocess.run(["git", "clone", "-q", "--branch", "main", str(self.origin), str(theirs)],
                       check=True, capture_output=True)
        (theirs / "CHANGELOG.md").write_text("# Changelog\n\n## [Unreleased]\n\n### Added\n\n- A\n- B\n",
                                             encoding="utf-8")
        git("-c", "user.email=o", "-c", "user.name=o", "commit", "-qam", "B", cwd=theirs)
        git("push", "-q", "origin", "main", cwd=theirs)

    def test_a_merged_tree_the_rules_refuse_does_not_land(self):
        outputs, done = self.carry_back()
        printed = done.stdout + done.stderr
        self.assertEqual(outputs.get("landed"), "false", printed)
        self.assertIn("changelog refused the result", printed)
        self.assertFalse(self.on_default_branch(self.tag))
        self.assertIn("pr create", self.gh_said())

    def test_the_branch_offered_is_the_one_from_before_the_merge(self):
        """The entry is put back under [Unreleased] in the pull request.

        So the pull request starts from the release as published, not from the merge that moved the entry.
        """
        outputs, done = self.carry_back()
        self.assertEqual(outputs.get("landed"), "false", done.stdout + done.stderr)
        offered = git("show", "release/0.1.0:CHANGELOG.md", cwd=self.origin).stdout
        self.assertNotIn("- B", offered)
        on_branch = git("log", "--format=%s", f"{self.tag}..release/0.1.0", cwd=self.origin).stdout.splitlines()
        self.assertEqual(on_branch, self.OPENED, "the release as published, with what the run wrote before merging")


class WhereTagsCarryNoPrefix(WhereAMergeRewritesTheReleasedSection):
    """`^none` says the tags have no prefix.

    Passed on as a literal prefix, it would match no release.
    The checks on the merged tree would then pass having compared nothing.
    """

    PREFIX = ""
    OPENED = []  # A source declaring no version has no next version to open.

    def carry_back(self, source="tags", tag_prefix="^none", fetch=True, check_workflow="ci.yml"):
        return super().carry_back(source=source, tag_prefix=tag_prefix, fetch=fetch, check_workflow=check_workflow)


class WhereTagsAreNamedDifferently(Staged):
    """The prefix is read from the source, not assumed.

    A repository tagging `release-0.1.0`, read as tagging `v*`, would keep the whole tag as the version.
    That is no version, and the run stops before anything is carried back.
    Under `release-`, cutting off everything before the first digit gives the same version.
    The subclass below is where the two differ.
    """

    def setUp(self):
        self.stage("release-")

    def test_only_the_declared_prefix_comes_off_the_tag(self):
        outputs, done = self.carry_back()
        self.assertEqual(outputs.get("version"), "0.1.0", done.stdout + done.stderr)
        self.assertEqual(outputs.get("landed"), "true")
        self.assertTrue(self.on_default_branch(self.tag))


class WhereThePrefixCarriesADigit(WhereTagsAreNamedDifferently):
    """`r2-v0.1.0`: what comes off is the declared prefix.

    Not everything before the first digit, and not everything up to a hyphen.
    """

    def setUp(self):
        self.stage("r2-v")


if __name__ == "__main__":
    unittest.main()
