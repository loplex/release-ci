"""Tests for rules/repository.py: which repository is checked, which tags are releases, and which are reachable.
Most run against repositories built for the purpose; check_ancestry, the rule over what git answered, runs over
plain booleans.

Run with `python3 -m unittest discover -s lib` from the repository root.
"""

import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from rules import repository
from rules.repository import check_ancestry, holder, released_versions, repository_root, unreachable

from .fixtures import TwoReleasesOneOffMain

SCRIPT = Path(__file__).resolve().parent.parent / "main.py"


class ReachableTags(unittest.TestCase):
    def test_tags_that_are_still_on_the_history_pass(self):
        self.assertEqual(check_ancestry({"0.1.0": True, "0.2.0": True}, "v"), [])

    def test_a_tag_a_rewrite_has_orphaned_is_caught(self):
        """A squash merge, a rebase merge, GitHub's `Update with rebase` and a force-push all do this to the
        release commit.
        The check asks about the result, not the cause, so it also holds for a way of rewriting a branch that
        nobody has thought of yet."""
        problems = check_ancestry({"0.1.0": True, "0.2.0": False}, "v")
        self.assertEqual(len(problems), 1)
        self.assertIn("v0.2.0", problems[0])

    def test_an_orphan_is_named_the_way_this_repository_tags(self):
        """Both spellings are in use, `v0.2.0` and a bare `0.2.0`.
        A report naming a tag nobody can look up sends its reader to the wrong place,
        whether or not a branch still holds the tag."""
        bare = check_ancestry({"0.2.0": False}, "")
        self.assertIn("0.2.0 is released", bare[0])
        self.assertNotIn("v0.2.0", bare[0])
        held = check_ancestry({"0.2.0": False}, "", {"0.2.0": "origin/release/0.2.0"})
        self.assertIn("0.2.0 is released", held[0])
        self.assertNotIn("v0.2.0", held[0])

    def test_every_orphan_is_reported_in_release_order(self):
        """Release order is precedence, and `0.10.0` sorts ahead of `0.9.0` as text."""
        problems = check_ancestry({"0.10.0": False, "0.9.0": False, "0.9.1": True}, "v")
        self.assertEqual(len(problems), 2)
        self.assertIn("v0.9.0", problems[0])
        self.assertIn("v0.10.0", problems[1])

    def test_a_repository_with_nothing_released_passes(self):
        self.assertEqual(check_ancestry({}, "v"), [])

    def test_a_branch_that_still_holds_the_tag_is_named_with_every_reading_the_squash_first(self):
        """A release on its way here is awaited before this rule (see AReleaseYetToLand in test_main.py).
        What reaches it with a branch holding the tag was most often squashed or rebased onto this history:
        both replay the release commit, and the branch holding the original stays.
        A rewritten base, or a release on its way that could not be recognized, are named after it."""
        problems = check_ancestry({"0.2.0": False}, "v", {"0.2.0": "origin/release/0.2.0"})
        self.assertEqual(len(problems), 1)
        self.assertIn("origin/release/0.2.0", problems[0])
        readings = [problems[0].index(said) for said in ("squash", "rewritten", "carried back")]
        self.assertEqual(readings, sorted(readings), problems[0])

    def test_an_orphan_no_branch_holds_is_still_blamed_on_a_rewrite(self):
        """The two cases are told apart by whether any branch holds the tag.
        A tag left behind by a rebase merge whose branch was then deleted is the easiest to mistake for the other
        case, and it still reads as a rewrite."""
        problems = check_ancestry({"0.2.0": False}, "v", {"0.2.0": ""})
        self.assertEqual(len(problems), 1)
        self.assertIn("rewrite", problems[0])


class WhichTagsCountAsReleases(unittest.TestCase):
    """A repository carries tags that are not releases, such as another component's or a deployment's.
    Its releases carry whichever spelling it tags with.
    Two things sort this out, and the tests below cover both:
    - the prefix, which a project tagging `v*` selects by and takes off;
    - the version pattern, which keeps `v0.1.0` out of a project that tags bare versions.
      The empty prefix selects `v0.1.0` and takes nothing off it, so only the pattern refuses it.
    Both mistakes pass.
    A wrong prefix yields no releases, and every check passes having compared nothing, with a note on stderr at
    most.
    A wrong pattern counts a tag of another kind as a release, with no note at all."""

    PLANTED = [
        "v0.1.0", "v1.2.3-rc.1", "v1.2", "version-1.0", "v2.0.0-SNAPSHOT",
        "0.1.0", "0.9.9", "10.1.0",
        "api/v9.9.9", "deploy/1.0.0", "milestone-2026-09",
    ]

    def releases_under(self, prefix):
        here = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        subprocess.run(["git", "init", "-q"], cwd=here, check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                        "commit", "-q", "--allow-empty", "-m", "init"], cwd=here, check=True)
        for tag in self.PLANTED:
            subprocess.run(["git", "tag", tag], cwd=here, check=True)
        original = repository.REPO
        repository.REPO = here
        self.addCleanup(setattr, repository, "REPO", original)
        return sorted(released_versions(prefix))

    def test_a_v_prefix_takes_the_v_tags_and_hands_back_versions(self):
        self.assertEqual(self.releases_under("v"), ["0.1.0", "1.2.3-rc.1", "2.0.0-SNAPSHOT"])

    def test_no_prefix_takes_the_bare_tags_and_leaves_the_v_ones(self):
        self.assertEqual(self.releases_under(""), ["0.1.0", "0.9.9", "10.1.0"])

    def test_the_prefix_selects_rather_than_merely_being_taken_off(self):
        """`10.1.0` tells the two readings apart.
        Selecting by what the tag starts with leaves it out of a `v` repository.
        Taking the prefix off whatever is listed would turn it into `0.1.0`:
        a second one, colliding silently with the release really tagged `v0.1.0`."""
        self.assertEqual(self.releases_under("v").count("0.1.0"), 1)

    def test_what_is_not_a_version_is_not_a_release_under_either(self):
        """`v1.2` has two numbers, and `version-1.0` merely starts with the letter.
        What each would come back as depends on the prefix:
        under `v` it is the tag with the prefix taken off, and under none it is the tag itself."""
        for prefix, two_numbers, merely_starts in (("v", "1.2", "ersion-1.0"), ("", "v1.2", "version-1.0")):
            with self.subTest(prefix=prefix):
                found = self.releases_under(prefix)
                self.assertNotIn(two_numbers, found)
                self.assertNotIn(merely_starts, found)

    def test_a_tag_on_a_version_being_worked_on_counts_as_a_release(self):
        """Somebody tagged a snapshot by hand: release-flow never makes such a tag.
        No rule here knows which suffix the version carried then, so it counts, as the pre-release it reads as.
        It ranks below the version itself, so that version can still be released."""
        self.assertIn("2.0.0-SNAPSHOT", self.releases_under("v"))

    def test_counting_none_out_of_many_is_said_out_loud(self):
        """This is what an unchecked prefix looks like from the outside.
        Every check then passes having compared nothing, except `version` under `tags`, which has no release to
        count from.
        It is said, not failed: a repository may carry only tags of other kinds."""
        said = io.StringIO()
        with contextlib.redirect_stderr(said):
            self.assertEqual(self.releases_under("nonesuch/"), [])
        self.assertIn("none of them is a release", said.getvalue())
        self.assertIn(f"{len(self.PLANTED)} tag(s)", said.getvalue())

    def test_a_prefix_that_selects_something_says_nothing(self):
        said = io.StringIO()
        with contextlib.redirect_stderr(said):
            self.assertTrue(self.releases_under("v"))
        self.assertEqual(said.getvalue(), "")

    def test_a_repository_with_no_tags_at_all_is_not_accused_of_anything(self):
        """A first release has nothing to be consistent with.
        That is not the same as having looked for releases in the wrong place."""
        empty = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        subprocess.run(["git", "init", "-q"], cwd=empty, check=True)
        original = repository.REPO
        repository.REPO = empty
        self.addCleanup(setattr, repository, "REPO", original)
        said = io.StringIO()
        with contextlib.redirect_stderr(said):
            self.assertEqual(released_versions("v"), [])
        self.assertEqual(said.getvalue(), "")

    def test_a_tag_of_another_kind_never_counts_even_when_it_ends_in_a_version(self):
        """Such a tag could come back two ways:
        whole, where nothing asks whether the tag is a version;
        or as the version it ends in, where whatever stands in front of it is taken off.
        Each is refused separately."""
        for prefix in ("v", ""):
            with self.subTest(prefix=prefix):
                found = self.releases_under(prefix)
                self.assertTrue(set(found).isdisjoint({"api/v9.9.9", "deploy/1.0.0", "milestone-2026-09"}),
                                found)
                self.assertTrue(set(found).isdisjoint({"9.9.9", "1.0.0"}), found)


class WhichRepositoryIsBeingChecked(unittest.TestCase):
    """The repository checked is the one the run is in, not the one this file lives in.
    Run from a checkout of this repository against another one, a root taken from the script's own path would
    name that checkout instead.
    It would do so silently, because that checkout has a CHANGELOG.md of its own for the checks to read."""

    def working_in(self, directory):
        self.enterContext(contextlib.chdir(directory))

    def test_the_root_is_the_repository_the_run_is_in(self):
        elsewhere = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        subprocess.run(["git", "init", "-q"], cwd=elsewhere, check=True)
        self.working_in(elsewhere)
        self.assertEqual(repository_root(), elsewhere)
        (elsewhere / "sub").mkdir()
        self.working_in(elsewhere / "sub")
        self.assertEqual(repository_root(), elsewhere, "the root, not the directory the run is in")

    def test_help_answers_outside_a_repository(self):
        """The repository is found when a subcommand first reads it, not when the file is loaded.
        Asking what the subcommands are should not require standing inside a repository."""
        nowhere = Path(self.enterContext(tempfile.TemporaryDirectory()))
        done = subprocess.run([sys.executable, str(SCRIPT), "--help"], cwd=nowhere, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("set-version", done.stdout)

    def test_a_subcommand_that_reads_the_repository_still_refuses_outside_one(self):
        nowhere = Path(self.enterContext(tempfile.TemporaryDirectory()))
        done = subprocess.run([sys.executable, str(SCRIPT), "prefix", "--version-source", "gradle.properties"],
                              cwd=nowhere, capture_output=True, text=True)
        self.assertEqual(done.returncode, 1)
        self.assertIn("inside the repository", done.stderr)

    def test_a_repository_missing_a_file_it_is_read_from_is_told_which(self):
        """A traceback is the wrong kind of loud: it reads as the tool breaking, and names no file to add."""
        empty = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        subprocess.run(["git", "init", "-q"], cwd=empty, check=True)
        for command, missing in (("prefix", "gradle.properties"), ("changelog", "CHANGELOG.md")):
            with self.subTest(command=command):
                done = subprocess.run([sys.executable, str(SCRIPT), command, "--version-source", "gradle.properties"],
                                      cwd=empty, capture_output=True, text=True)
                self.assertEqual(done.returncode, 1)
                self.assertNotIn("Traceback", done.stderr)
                self.assertIn(f"there is no {missing} here", done.stderr)

    def test_a_file_that_does_not_decode_is_told_which_and_on_which_line(self):
        """The line is counted as CommonMark counts it, a CR alone ending one too."""
        here = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        subprocess.run(["git", "init", "-q"], cwd=here, check=True)
        lines = [b"# Changelog", b"", b"## [Unreleased]", b"", b"- entry", b"- caf\xe9", b""]
        for ending in (b"\n", b"\r\n", b"\r"):
            (here / "CHANGELOG.md").write_bytes(ending.join(lines))
            for arguments in (["changelog", "--version-source", "tags", "--tag-prefix", "v"], ["notes", "0.1.0"]):
                with self.subTest(ending=ending, command=arguments[0]):
                    done = subprocess.run([sys.executable, str(SCRIPT), *arguments], cwd=here, capture_output=True,
                                          text=True)
                    self.assertEqual(done.returncode, 1)
                    self.assertNotIn("Traceback", done.stderr)
                    self.assertIn("CHANGELOG.md line 6 holds a byte that is not utf-8", done.stderr)

    def test_running_outside_a_repository_is_refused(self):
        nowhere = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.working_in(nowhere)
        with self.assertRaises(SystemExit):
            repository_root()


class WhichBranchHoldsATag(TwoReleasesOneOffMain):
    """Which releases this history reaches, and which branch holds one it does not reach.
    Both exist for a release tagged on a branch this history has not taken in yet."""

    def test_only_a_release_off_this_history_is_unreachable(self):
        self.assertEqual(unreachable("v", ["0.1.0", "0.2.0"]), {"0.2.0"})

    def test_the_release_branch_is_named_ahead_of_another_holding_the_tag(self):
        """`aside` sorts first, so a holder that did not put the release branch first would name `aside`."""
        self.assertEqual(holder("v0.2.0", "0.2.0"), "release/0.2.0")

    def test_the_remote_s_branch_is_named_ahead_of_a_local_one(self):
        """A release is carried back from what the remote has.
        So the remote's branch is named, as fetched, even where a local branch of the same name holds the tag too."""
        self.git("update-ref", "refs/remotes/origin/release/0.2.0", "v0.2.0")
        self.assertEqual(holder("v0.2.0", "0.2.0"), "origin/release/0.2.0")

    def test_a_remote_branch_of_another_name_is_named_ahead_of_the_local_release_branch(self):
        """Once a remote branch holds the tag, only the remote's branches are sorted, whatever the remote is called.
        The local release branch is not pulled ahead of them."""
        self.git("update-ref", "refs/remotes/upstream/aside", "v0.2.0")
        self.assertEqual(holder("v0.2.0", "0.2.0"), "upstream/aside")

    def test_a_branch_merely_ending_in_the_release_branch_s_name_is_not_taken_for_it(self):
        """`prerelease/0.2.0` sorts before `release/0.2.0` and ends in its name.
        So only a whole component of a branch name counts as the release branch."""
        self.git("branch", "prerelease/0.2.0", "v0.2.0")
        self.assertEqual(holder("v0.2.0", "0.2.0"), "release/0.2.0")

    def test_the_remote_s_release_branch_is_named_ahead_of_another_remote_branch(self):
        """`origin/aside` sorts first, so a holder that took only `release/0.2.0` itself would name it."""
        self.git("update-ref", "refs/remotes/origin/aside", "v0.2.0")
        self.git("update-ref", "refs/remotes/origin/release/0.2.0", "v0.2.0")
        self.assertEqual(holder("v0.2.0", "0.2.0"), "origin/release/0.2.0")

    def test_a_branch_whose_path_ends_in_the_release_branch_s_name_is_named_ahead_of_another(self):
        """Only a message names it, so `team/release/0.2.0` is taken for the release branch here.
        Whether a release is awaited is release_branch's to say, and it takes no such branch."""
        self.git("branch", "-m", "release/0.2.0", "team/release/0.2.0")
        self.assertEqual(holder("v0.2.0", "0.2.0"), "team/release/0.2.0")
