#!/usr/bin/env python3
"""Tests for the rules check-release.py holds.

Most tests exercise the rules over text, without a repository.
The helpers that talk to git are tested against a repository built for the purpose.

Run with `python3 -m unittest discover` over the directory this file sits in.
"""

import argparse
import contextlib
import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "check-release.py"
specification = importlib.util.spec_from_file_location("check_release", SCRIPT)
check_release = importlib.util.module_from_spec(specification)
specification.loader.exec_module(check_release)

check_version = check_release.check_version
check_changelog = check_release.check_changelog
precedence = check_release.precedence
version_after = check_release.version_after
check_ancestry = check_release.check_ancestry
channel_of = check_release.channel_of
uncompared = check_release.uncompared
closed = check_release.closed
linked = check_release.linked
sections = check_release.sections
being_worked_on = check_release.being_worked_on
repository_root = check_release.repository_root
prefix_from = check_release.prefix_from
version_command = check_release.version_command
next_candidate = check_release.next_candidate
asked_by = check_release.asked_by
check_step = check_release.check_step
train_asks = check_release.train_asks
Asked = check_release.Asked
PATCH, MINOR, MAJOR = check_release.PATCH, check_release.MINOR, check_release.MAJOR
SEMVER = check_release.SEMVER


class Precedence(unittest.TestCase):
    def test_a_release_outranks_its_own_pre_releases(self):
        self.assertGreater(precedence("0.2.0"), precedence("0.2.0-rc.1"))

    def test_a_numeric_identifier_is_compared_as_a_number(self):
        self.assertLess(precedence("0.2.0-beta.9"), precedence("0.2.0-beta.10"))

    def test_a_numeric_identifier_ranks_below_an_alphanumeric_one(self):
        """The spec's rule, which reads backwards when compared as text.
        `1.0.0-9` is an earlier step than `1.0.0-10a`, but `sorted` over the strings puts it after."""
        self.assertLess(precedence("1.0.0-9"), precedence("1.0.0-10a"))

    def test_build_metadata_does_not_figure_into_precedence(self):
        """SemVer says two versions that differ only in build metadata have the same precedence.
        The README beside this file quotes that rule.
        Ranking by metadata would order releases by a field the spec says orders nothing."""
        self.assertEqual(precedence("1.0.0+a"), precedence("1.0.0+b"))
        self.assertEqual(precedence("1.0.0"), precedence("1.0.0+dfsg1"))
        self.assertLess(precedence("1.0.0-rc.1+z"), precedence("1.0.0+a"))

    def test_more_identifiers_outrank_fewer_when_the_ones_before_are_equal(self):
        self.assertLess(precedence("0.2.0-rc.1"), precedence("0.2.0-rc.1.1"))

    def test_the_numbers_come_before_the_suffix(self):
        self.assertLess(precedence("0.9.9"), precedence("1.0.0-rc.1"))


class WhatCountsAsAVersion(unittest.TestCase):
    """The grammar is SemVer 2.0.0's, and both directions are tested.
    A shape the spec allows but this refused would be a release nobody could name.
    A shape the spec leaves undefined but this took would be ordered by rules nobody wrote down."""

    def test_the_shapes_the_spec_defines_are_taken(self):
        for version in ("1.0.0", "0.0.0", "1.0.0-alpha", "1.0.0-eap-2", "1.0.0-0.3.7", "1.0.0-x.7.z.92"):
            with self.subTest(version=version):
                self.assertTrue(SEMVER.match(version))

    def test_a_leading_zero_is_refused(self):
        for version in ("01.0.0", "1.00.0", "1.0.01", "1.0.0-01"):
            with self.subTest(version=version):
                self.assertIsNone(SEMVER.match(version))

    def test_an_empty_identifier_is_refused(self):
        for version in ("1.0.0-", "1.0.0-.", "1.0.0-a..b", "1.0.0-alpha."):
            with self.subTest(version=version):
                self.assertIsNone(SEMVER.match(version))

    def test_digits_are_ascii_ones(self):
        """`\\d` alone takes any script's digits, and precedence would then order `1٠.0.0` as 10.0.0."""
        for version in ("1\u0660.0.0", "1.1\u0660.0", "1.0.0-rc.1\u0660"):
            with self.subTest(version=version):
                self.assertIsNone(SEMVER.match(version))

    def test_a_trailing_newline_is_not_part_of_a_version(self):
        self.assertIsNone(SEMVER.match("1.0.0\n"))

    def test_build_metadata_is_taken(self):
        """The spec's own examples, plus the Debian-style repackage suffix.
        Build metadata identifiers are looser than pre-release ones: a leading zero is allowed, because nothing
        counts them."""
        for version in ("1.0.0+build.1", "1.0.0-rc.1+build.1", "1.0.0+dfsg1", "1.0.0+001",
                        "1.0.0+21AF26D3----117B344092BD"):
            with self.subTest(version=version):
                self.assertTrue(SEMVER.match(version))

    def test_an_empty_build_identifier_is_refused(self):
        for version in ("1.0.0+", "1.0.0+.", "1.0.0+a..b", "1.0.0+build."):
            with self.subTest(version=version):
                self.assertIsNone(SEMVER.match(version))


class FirstRelease(unittest.TestCase):
    def test_anything_valid_may_be_the_first(self):
        self.assertEqual(check_version("0.1.0", []), [])
        self.assertEqual(check_version("7.3.1", []), [])

    def test_a_version_that_is_not_one_is_refused(self):
        for candidate in ("0.2", "v0.2.0", "0.2.0.1"):
            with self.subTest(candidate=candidate):
                problems = check_version(candidate, [])
                self.assertEqual(len(problems), 1)
                self.assertIn("is not a version this project releases", problems[0])


class AVersionBeingWorkedOn(unittest.TestCase):
    """The marker says the version has not been released, so it can never be a release.
    This is the rule most easily hit by accident.
    A script that appends -SNAPSHOT to a version that already has it writes `1.0.0-SNAPSHOT-SNAPSHOT`.
    `version` takes the marker off once, and would then offer `1.0.0-SNAPSHOT` as the release."""

    def test_the_marker_is_refused_wherever_it_sits_in_the_suffix(self):
        for candidate in ("1.0.0-SNAPSHOT", "1.0.0-rc.1-SNAPSHOT", "1.0.0-rc.SNAPSHOT", "1.0.0-SNAPSHOT-SNAPSHOT",
                          "1.0.0-SNAPSHOT+b", "1.0.0-SNAPSHOT.2"):
            with self.subTest(candidate=candidate):
                problems = check_version(candidate, ["0.9.0"])
                self.assertEqual(len(problems), 1)
                self.assertIn("being worked on", problems[0])

    def test_an_identifier_that_merely_contains_the_word_is_not_the_marker(self):
        self.assertFalse(being_worked_on("1.0.0-preSNAPSHOT"))
        self.assertFalse(being_worked_on("1.0.0-SNAPSHOTTED"))

    def test_the_word_in_build_metadata_is_not_the_marker(self):
        """Metadata names a build, not a state."""
        self.assertFalse(being_worked_on("1.0.0+SNAPSHOT"))


class TheStep(unittest.TestCase):
    def test_the_three_successors_are_allowed(self):
        for candidate in ("1.2.4", "1.3.0", "2.0.0"):
            with self.subTest(candidate=candidate):
                self.assertEqual(check_version(candidate, ["1.2.3"]), [])

    def test_a_skipped_number_is_refused(self):
        self.assertTrue(check_version("1.4.0", ["1.2.3"]))

    def test_a_part_that_is_not_zeroed_is_refused(self):
        self.assertTrue(check_version("1.3.1", ["1.2.3"]))

    def test_the_version_already_released_is_refused(self):
        self.assertTrue(check_version("1.2.3", ["1.2.3"]))

    def test_going_backwards_is_refused(self):
        self.assertTrue(check_version("1.2.2", ["1.2.3"]))


class ThePreReleaseTrain(unittest.TestCase):
    def test_a_pre_release_may_open_a_permitted_core(self):
        self.assertEqual(check_version("0.2.0-rc.1", ["0.1.0"]), [])

    def test_the_train_may_go_on_without_advancing_the_core(self):
        self.assertEqual(check_version("0.2.0-rc.2", ["0.1.0", "0.2.0-rc.1"]), [])

    def test_the_train_may_end_in_the_release_it_was_for(self):
        self.assertEqual(check_version("0.2.0", ["0.1.0", "0.2.0-rc.1", "0.2.0-rc.2"]), [])

    def test_re_releasing_a_tagged_pre_release_is_refused(self):
        """The equal case of "comes after", where the step check has nothing to say.
        0.2.0-rc.1 lies inside a core that 0.1.0 permits.
        So only `<=` stops a tagged pre-release from being released twice."""
        problems = check_version("0.2.0-rc.1", ["0.1.0", "0.2.0-rc.1"])
        self.assertEqual(len(problems), 1)
        self.assertIn("does not come after", problems[0])

    def test_going_backwards_inside_the_train_is_refused(self):
        self.assertTrue(check_version("0.2.0-rc.1", ["0.1.0", "0.2.0-rc.2"]))

    def test_a_stable_hotfix_may_go_out_while_a_train_is_open(self):
        """0.1.1 goes to everyone, so it only has to outrank the last release everyone was offered, 0.1.0.
        Subscribers who see 0.2.0-rc.1 are not offered a downgrade either: 0.1.1 sorts below the rc."""
        self.assertEqual(check_version("0.1.1", ["0.1.0", "0.2.0-rc.1"]), [])

    def test_a_hotfix_does_not_close_the_train(self):
        releases = ["0.1.0", "0.2.0-rc.1", "0.1.1"]
        self.assertEqual(check_version("0.2.0-rc.2", releases), [])
        self.assertEqual(check_version("0.2.0", releases), [])

    def test_a_pre_release_has_to_outrank_every_tag(self):
        """Channel subscribers see every release.
        A pre-release below the highest tag would never be offered to them, so it is refused."""
        problems = check_version("0.1.2-rc.1", ["0.1.0", "0.1.1", "0.2.0-rc.1"])
        self.assertTrue(problems)
        self.assertIn("0.2.0-rc.1", problems[0])
        # Listed by name, as `git tag -l` lists them: 0.10.0-rc.1 comes first, and is still the highest.
        problems = check_version("0.9.2-rc.1", ["0.10.0-rc.1", "0.9.0", "0.9.1"])
        self.assertTrue(problems)
        self.assertIn("0.10.0-rc.1", problems[0])

    def test_a_hotfix_cannot_be_tried_on_a_channel_while_a_train_is_open(self):
        """The cost of the rule above.
        0.1.1 may go out, but 0.1.1-rc.1 sorts below 0.2.0-rc.1, so the hotfix cannot be tried on a channel first.
        Tested here so that nobody learns it from a failed run."""
        problems = check_version("0.1.1-rc.1", ["0.1.0", "0.2.0-rc.1"])
        self.assertTrue(problems)
        self.assertIn("0.2.0-rc.1", problems[0])

    def test_with_nothing_final_released_the_open_train_is_the_only_way_on(self):
        """With nothing final released there is no step to take, so the open train is the only way on.
        Without this, a project that has only tagged pre-releases could name any core at all:
        the step check reads the last final release, and there is none."""
        self.assertEqual(check_version("0.2.0-rc.2", ["0.2.0-rc.1"]), [])
        self.assertEqual(check_version("0.2.0", ["0.2.0-rc.1"]), [])
        for candidate in ("0.2.1", "0.3.0", "9.9.9"):
            with self.subTest(candidate=candidate):
                problems = check_version(candidate, ["0.2.0-rc.1"])
                self.assertTrue(problems)
                self.assertIn("does not follow 0.2.0-rc.1: the next version is 0.2.0", problems[0])

    def test_a_final_release_still_has_to_outrank_the_last_final_one(self):
        problems = check_version("0.1.1", ["0.1.0", "0.2.0-rc.1", "0.2.0"])
        self.assertTrue(problems)
        self.assertIn("0.2.0", problems[0])
        # Listed by name, as `git tag -l` lists them, the last final release is not the last one listed.
        problems = check_version("0.9.1", ["0.10.0", "0.9.0"])
        self.assertTrue(problems)
        self.assertIn("does not come after 0.10.0", problems[0])
        self.assertEqual(check_version("0.10.1", ["0.10.0", "0.9.0"]), [])

    def test_an_open_train_does_not_widen_the_step(self):
        """The step is measured from the last final release, and an open train does not move it.
        Past 0.1.0 the step is still one of 0.1.1, 0.2.0 and 1.0.0, and 0.3.0 is none of them."""
        problems = check_version("0.3.0", ["0.1.0", "0.2.0-rc.1"])
        self.assertTrue(problems)
        self.assertIn("does not follow 0.1.0", problems[0])
        self.assertEqual(check_version("1.0.0", ["0.1.0", "0.2.0-rc.1"]), [])


class TwoBuildsOfOneVersion(unittest.TestCase):
    """What accepting build metadata costs.
    SemVer leaves metadata out of ordering, so `1.0.0+b` does not outrank `1.0.0+a`.
    A release that outranks nothing is never offered by an update check, so it is refused.
    The refusal names the metadata rather than saying `does not come after`.
    About a version that plainly came later, that wording would read as a bug."""

    def test_two_builds_of_one_version_are_refused_by_name(self):
        problems = check_version("1.0.0+b", ["1.0.0+a"])
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("differ only in build metadata", problems[0])
        self.assertNotIn("does not come after", problems[0])

    def test_dropping_the_metadata_is_no_release_either(self):
        problems = check_version("1.0.0", ["1.0.0+dfsg1"])
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("differ only in build metadata", problems[0])

    def test_re_releasing_the_very_same_text_still_reads_as_released_already(self):
        """The neighboring case, which is not about metadata: nothing differs, so there is no ordering to explain."""
        problems = check_version("1.0.0+a", ["1.0.0+a"])
        self.assertIn("does not come after", problems[0])
        self.assertEqual(len(problems), 2, problems)

    def test_metadata_does_not_change_which_core_may_follow(self):
        self.assertEqual(check_version("1.0.1+b", ["1.0.0+a"]), [])
        self.assertEqual(check_version("1.0.1", ["1.0.0+a"]), [])


class WhatFollowsARelease(unittest.TestCase):
    def test_a_final_release_is_followed_by_a_patch(self):
        self.assertEqual(version_after("0.1.1"), "0.1.2")
        self.assertEqual(version_after("1.9.0"), "1.9.1")

    def test_what_follows_is_bare_and_the_source_adds_its_marker(self):
        """`-SNAPSHOT` is Gradle's marker for a version being worked on.
        A repository versioned by its tags has no such state, so what follows a release there is the bare version.
        That is also what `version` takes under `tags` when no version is given."""
        self.assertEqual(self.next_after("v0.1.1", "gradle.properties"), ([], "0.1.2-SNAPSHOT"))
        self.assertEqual(self.next_after("v0.1.1", "tags"), ([], "0.1.2"))

    def next_after(self, released, source):
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            problems = check_release.next_command(argparse.Namespace(released=released, version_source=source,
                                                                     tag_prefix="v"))
        return problems, printed.getvalue().strip()

    def test_a_pre_release_goes_on_heading_for_the_release_it_was_for(self):
        """0.2.0-rc.1 was a step toward 0.2.0, so work carries on toward it.
        Counting up the patch would skip the release the train was heading for.
        The step check would then refuse 0.2.1, the version that counting would give."""
        self.assertEqual(version_after("0.2.0-rc.1"), "0.2.0")
        self.assertEqual(version_after("0.2.0-beta.1"), "0.2.0")

    def test_build_metadata_is_not_carried_into_what_follows(self):
        """Metadata names a build; what follows a release is not that build."""
        self.assertEqual(version_after("1.0.0+dfsg1"), "1.0.1")
        self.assertEqual(version_after("0.2.0-rc.1+sha.5114f85"), "0.2.0")

    def test_what_follows_may_itself_be_released(self):
        """The two rules have to agree: what follows a release must be something the step check accepts."""
        for released, releases in (("0.1.1", ["0.1.0", "0.1.1"]), ("0.2.0-rc.1", ["0.1.0", "0.2.0-rc.1"])):
            with self.subTest(released=released):
                self.assertEqual(check_version(version_after(released), releases), [])


class WhatUnreleasedAsksFor(unittest.TestCase):
    """How far each kind of change under [Unreleased] moves the version.
    The steps are SemVer's rules 6 to 8, applied to Keep a Changelog's kinds.
    An entry marked **BREAKING** asks for a major step under any group."""

    def test_each_kind_asks_for_its_step(self):
        for kind, step in (("Added", MINOR), ("Changed", MINOR), ("Deprecated", MINOR), ("Removed", MAJOR),
                           ("Fixed", PATCH), ("Security", PATCH)):
            with self.subTest(kind=kind):
                self.assertEqual(asked_by(f"### {kind}\n\n- X\n").step, step)

    def test_the_largest_step_is_asked_and_named(self):
        asked = asked_by("### Fixed\n\n- F\n\n### Added\n\n- A\n\n### Security\n\n- S\n")
        self.assertEqual((asked.step, asked.why), (MINOR, "### Added"))

    def test_an_empty_group_asks_for_nothing(self):
        """A `### Removed` left as a reminder removes nothing, and neither does a comment in it."""
        self.assertEqual(asked_by("### Removed\n\n### Fixed\n\n- F\n").step, PATCH)
        self.assertEqual(asked_by("### Removed\n\n<!-- nothing yet -->\n\n### Fixed\n\n- F\n").step, PATCH)

    def test_an_entry_marked_breaking_asks_for_a_major_under_any_group(self):
        for text in ("### Changed\n\n- **BREAKING** the input is required\n",
                     "### Fixed\n\n- **BREAKING:** a wrong answer is refused now\n",
                     "### Dependencies\n\n1. **Breaking** raised to Java 21\n",
                     "### Changed\n\n- A\n  - **BREAKING** and a nested one\n"):
            with self.subTest(text=text):
                asked = asked_by(text)
                self.assertEqual(asked.step, MAJOR)
                self.assertTrue(asked.why.startswith("an entry marked **BREAKING** under ### "), asked.why)

    def test_breaking_counts_only_where_an_entry_starts(self):
        self.assertEqual(asked_by("### Fixed\n\n- a note that is **BREAKING** nothing\n").step, PATCH)
        self.assertEqual(asked_by("### Fixed\n\n- a line wrapped so that its next one starts with\n"
                                  "  **BREAKING** is not an entry\n").step, PATCH)

    def test_a_group_of_another_name_asks_for_a_patch_and_is_named(self):
        """Keep a Changelog allows groups of other names.
        The ones people add, such as Documentation or Dependencies, are not new functionality.
        They are named, so that `### Add`, a feature filed under a typo, can be seen."""
        asked = asked_by("### Documentation\n\n- D\n\n### Add\n\n- A\n\n### Fixed\n\n- F\n")
        self.assertEqual((asked.step, asked.unknown), (PATCH, ["Documentation", "Add"]))
        # A group whose entry is marked BREAKING asks for more than a patch, so it is not named.
        self.assertEqual(asked_by("### Dependencies\n\n- **BREAKING** Java 21\n").unknown, [])

    def test_an_entry_under_no_group_is_handed_back_and_other_text_is_not(self):
        asked = asked_by("<!-- keep this short -->\nWhat follows is not released yet.\n\n- loose\n\n### Fixed\n\n- F\n")
        self.assertEqual(asked.loose, ["- loose"])
        self.assertEqual(asked_by("- only this\n").loose, ["- only this"])
        self.assertEqual(asked_by("").loose, [])
        self.assertEqual(asked_by("<!--\n- a template\n-->\n\n- - -\n***\n\n### Fixed\n\n- F\n").loose, [],
                         "a comment over several lines, and a thematic break, are not entries")

    def test_a_group_heading_is_read_as_commonmark_reads_one(self):
        """Each of these is a heading to CommonMark, and starts a group of its own:
        up to three spaces of indent, a tab after the #s, a closing run of #s.
        Its entries then do not count under the group above it."""
        for heading in ("   ### Added", "###\tAdded", "### Added ###", "### Added\t#"):
            with self.subTest(heading=heading):
                asked = asked_by(f"### Fixed\n\n- F\n\n{heading}\n\n- A\n")
                self.assertEqual((asked.step, asked.why, asked.unknown), (MINOR, "### Added", []))
        self.assertEqual(asked_by("### Fixed\n\n- F\n\n    ### Added\n\n- A\n").step, PATCH,
                         "four spaces make a code block, not a heading")
        self.assertEqual(asked_by("### Added#\n\n- A\n").unknown, ["Added#"],
                         "a # with no space before it is part of the text")


class WhatAnOpenTrainAsksFor(unittest.TestCase):
    """train_asks: a branch whose changelog holds the sections of an open train carries that train's changes.
    A release cut from it is held to them as well as to [Unreleased]."""

    RELEASES = ["0.2.0-beta.1", "0.2.0", "0.3.0-beta.1"]

    def test_a_pre_release_above_the_last_final_release_asks_as_much_as_it_holds(self):
        found = {"Unreleased": "### Fixed\n\n- F", "0.3.0-beta.1": "### Added\n\n- A", "0.2.0": "### Fixed\n\n- G"}
        asked = train_asks(found, self.RELEASES)
        self.assertEqual((asked.step, asked.why, asked.where), (MINOR, "### Added", "[0.3.0-beta.1]"))

    def test_what_the_last_final_release_already_took_in_asks_for_nothing(self):
        """0.2.0 is the release the step is measured from, and 0.2.0-beta.1 comes before it."""
        found = {"Unreleased": "### Fixed\n\n- F", "0.2.0": "### Removed\n\n- R", "0.2.0-beta.1": "### Removed\n\n- R"}
        self.assertEqual(train_asks(found, self.RELEASES).where, "[Unreleased]")
        self.assertEqual(train_asks(found, self.RELEASES).step, PATCH)

    def test_unreleased_is_named_where_it_asks_as_much(self):
        found = {"Unreleased": "### Added\n\n- A", "0.3.0-beta.1": "### Added\n\n- B"}
        self.assertEqual(train_asks(found, self.RELEASES).where, "[Unreleased]")


class TheStepWhatIsReleasedAsksFor(unittest.TestCase):
    """check_step: a release has to move past the last final release by at least the step [Unreleased] asks."""

    ADDED = Asked(MINOR, "### Added", [], [])
    REMOVED = Asked(MAJOR, "### Removed", [], [])

    def test_a_patch_over_an_addition_is_refused_and_the_minor_named(self):
        problems = check_step("0.2.1", ["0.1.0", "0.2.0"], self.ADDED)
        self.assertEqual(problems, ["[Unreleased] holds ### Added, so the release after 0.2.0 is at least a minor, "
                                    "0.3.0, and 0.2.1 is not"])
        self.assertEqual(check_step("0.3.0", ["0.2.0"], self.ADDED), [])
        self.assertEqual(check_step("1.0.0", ["0.2.0"], self.ADDED), [])

    def test_a_patch_is_asked_of_nothing_more(self):
        self.assertEqual(check_step("0.2.1", ["0.2.0"], Asked(PATCH, "", [], [])), [])

    def test_below_1_0_a_breaking_change_moves_the_minor(self):
        self.assertEqual(check_step("0.3.0", ["0.2.0"], self.REMOVED), [])
        self.assertIn("at least a minor, 0.3.0", check_step("0.2.1", ["0.2.0"], self.REMOVED)[0])

    def test_from_1_0_a_breaking_change_moves_the_major(self):
        self.assertIn("at least a major, 2.0.0", check_step("1.3.0", ["1.2.0"], self.REMOVED)[0])
        self.assertEqual(check_step("2.0.0", ["1.2.0"], self.REMOVED), [])

    def test_a_pre_release_is_measured_from_the_last_final_release(self):
        """The step is measured on the core, as check_version measures it.
        A pre-release of a version that would pass passes; one of a version that would not is refused.
        That holds with or without an open train."""
        self.assertEqual(check_step("0.3.0-beta.1", ["0.2.0"], self.ADDED), [])
        self.assertTrue(check_step("0.2.1-beta.1", ["0.2.0"], self.ADDED))
        self.assertEqual(check_step("0.3.0", ["0.2.0", "0.3.0-beta.1"], self.ADDED), [])

    def test_with_nothing_final_there_is_no_step_to_measure(self):
        self.assertEqual(check_step("0.1.0", [], self.ADDED), [])
        self.assertEqual(check_step("0.1.0", ["0.1.0-rc.1"], self.ADDED), [])

    def test_a_version_that_is_no_step_at_all_is_left_to_check_version(self):
        self.assertEqual(check_step("0.5.0", ["0.2.0"], self.ADDED), [])
        self.assertEqual(check_step("0.2.0", ["0.2.0"], self.ADDED), [])


class TheChannel(unittest.TestCase):
    """What the pre-release suffix is for.
    A project whose build also names the channel spells this rule a second time there.
    The two have to agree: the channel uploaded to and the channel asked for afterwards must be the same."""

    def test_a_final_release_goes_to_everyone(self):
        self.assertEqual(channel_of("0.3.0"), "default")

    def test_a_pre_release_goes_to_the_channel_its_suffix_names(self):
        self.assertEqual(channel_of("0.3.0-beta.1"), "beta")
        self.assertEqual(channel_of("1.0.0-rc.2"), "rc")
        self.assertEqual(channel_of("1.0.0-eap"), "eap")

    def test_a_hyphen_does_not_separate_identifiers(self):
        """`1.0.0-eap-2` and `1.0.0-eap.2` are both valid, and here they mean different things.
        The channel is the first dot-separated identifier, so the hyphenated spelling names a channel per build.
        Tested so that nobody meets it as a build uploaded to a channel nobody subscribes to."""
        self.assertEqual(channel_of("1.0.0-eap.2"), "eap")
        self.assertEqual(channel_of("1.0.0-eap-2"), "eap-2")

    def test_build_metadata_is_not_part_of_the_channel(self):
        self.assertEqual(channel_of("1.0.0+dfsg1"), "default")
        self.assertEqual(channel_of("0.3.0-beta.1+sha.5114f85"), "beta")
        # A pre-release with no dot before the `+`, and metadata holding a hyphen.
        # If the metadata were not cut off first, the first would read `beta+sha`, and the second would name
        # the channel `7`.
        self.assertEqual(channel_of("0.3.0-beta+sha.5114f85"), "beta")
        self.assertEqual(channel_of("1.0.0+build-7"), "default")

    def test_the_version_being_worked_on_has_a_channel_by_the_same_rule(self):
        """Nothing carrying -SNAPSHOT is released: `version` refuses it, and released_versions() leaves out
        such a tag.
        The rule still has to answer the way a second copy of it elsewhere would.
        With any `+` metadata off, everything after the first `-`, up to the first `.`, is the channel."""
        self.assertEqual(channel_of("0.2.1-SNAPSHOT"), "SNAPSHOT")

    def test_a_version_is_asked_about_bare(self):
        """channel takes no tag prefix, so a tag's name is refused rather than read with the prefix guessed."""
        for version, answer in (("0.3.0-beta.1", ([], "beta\n")),
                                ("v0.3.0-beta.1", (["'v0.3.0-beta.1' is not a version; channel takes one "
                                                    "without the tag prefix"], ""))):
            with self.subTest(version=version):
                printed = io.StringIO()
                with contextlib.redirect_stdout(printed):
                    problems = check_release.channel_command(argparse.Namespace(version=version))
                self.assertEqual((problems, printed.getvalue()), answer)

    def test_a_command_refuses_the_options_it_never_reads(self):
        """notes and channel read neither option, and set-version names no tag, so it takes no --tag-prefix."""
        for arguments in (["notes", "0.1.0", "--version-source", "tags"], ["notes", "0.1.0", "--tag-prefix", "v"],
                          ["channel", "0.1.0", "--version-source", "tags"], ["channel", "0.1.0", "--tag-prefix", "v"],
                          ["set-version", "0.1.0", "--version-source", "tags", "--tag-prefix", "v"]):
            with self.subTest(arguments=arguments):
                done = subprocess.run([sys.executable, str(SCRIPT), *arguments], capture_output=True, text=True)
                self.assertEqual(done.returncode, 2, done.stderr)
                self.assertIn("unrecognized arguments", done.stderr)


class ReleasedSections(unittest.TestCase):
    AT_TAG = """# Changelog

## [Unreleased]

## [0.1.0] - 2026-09-15

### Added

- A
- B

[0.1.0]: https://example.invalid/commits/v0.1.0
"""

    def test_an_untouched_section_passes(self):
        self.assertEqual(check_changelog(self.AT_TAG, {"0.1.0": self.AT_TAG}), [])

    def test_work_added_under_unreleased_is_free(self):
        head = self.AT_TAG.replace("## [Unreleased]\n", "## [Unreleased]\n\n### Added\n\n- C\n")
        self.assertEqual(check_changelog(head, {"0.1.0": self.AT_TAG}), [])

    def test_the_link_definitions_are_not_part_of_a_section(self):
        head = self.AT_TAG.replace(
            "[0.1.0]: https://example.invalid/commits/v0.1.0",
            "[Unreleased]: https://example.invalid/compare/v0.1.0...HEAD\n"
            "[0.1.0]: https://example.invalid/commits/v0.1.0",
        )
        self.assertEqual(check_changelog(head, {"0.1.0": self.AT_TAG}), [])

    def test_an_entry_merged_into_a_released_section_is_caught(self):
        """The hazard this check exists for.
        A three-way merge can put an entry added to [Unreleased] after the branch point into the released
        section instead.
        It does so cleanly, without a conflict."""
        head = self.AT_TAG.replace("- B\n", "- B\n- C\n")
        self.assertTrue(check_changelog(head, {"0.1.0": self.AT_TAG}))

    def test_a_reworded_released_entry_is_caught(self):
        head = self.AT_TAG.replace("- A\n", "- A, said better\n")
        self.assertTrue(check_changelog(head, {"0.1.0": self.AT_TAG}))

    def test_a_section_that_has_gone_is_caught(self):
        head = "# Changelog\n\n## [Unreleased]\n"
        self.assertTrue(check_changelog(head, {"0.1.0": self.AT_TAG}))

    def test_a_tag_older_than_the_section_is_passed_over(self):
        before = "# Changelog\n\n## [Unreleased]\n"
        self.assertEqual(check_changelog(self.AT_TAG, {"0.1.0": before}), [])

    def test_a_tag_older_than_its_section_is_listed_as_uncompared(self):
        """uncompared() names every version whose tag holds no text of its section, and only those.
        What the report does with that list is tested in AskingTheRepository."""
        before = "# Changelog\n\n## [Unreleased]\n"
        later = self.AT_TAG.replace("[0.1.0]", "[0.2.0]")
        self.assertEqual(uncompared({"0.1.0": before, "0.2.0": later}), ["0.1.0"])
        self.assertEqual(uncompared({"0.1.0": self.AT_TAG}), [])

    def test_a_section_missing_while_its_release_is_off_this_history_is_not_called_deleted(self):
        """A release is published before its branch reaches the default branch.
        In between, the section exists only where the tag is.
        `ancestry` already fails for that.
        Saying the section is gone as well would read as a second, separate claim that somebody deleted text."""
        problems = check_changelog("# Changelog\n\n## [Unreleased]\n", {"0.1.0": self.AT_TAG}, {"0.1.0"})
        self.assertEqual(len(problems), 1)
        self.assertNotIn("is gone", problems[0])
        self.assertIn("has yet to reach here", problems[0])

    def test_a_section_missing_while_its_release_is_on_this_history_is_a_deletion(self):
        problems = check_changelog("# Changelog\n\n## [Unreleased]\n", {"0.1.0": self.AT_TAG}, set())
        self.assertEqual(len(problems), 1)
        self.assertIn("is gone", problems[0])


class ClosingTheUnreleasedSection(unittest.TestCase):
    """What a release does to the changelog before it is released; the counterpart of check_changelog.
    What this writes is what the tag will hold a copy of, and it may never be edited afterwards."""

    FOLLOWED = "# Log\n\n## [Unreleased]\n\n### Added\n\n- X\n\n## [0.1.0] - 2026-01-01\n\n- old\n"
    LINKED = "# Log\n\n## [Unreleased]\n\n### Added\n\n- X\n\n\n\n[Unreleased]: https://example.invalid/x\n"

    def test_the_entries_become_a_section_of_their_own(self):
        """The date stays part of the section, because `sections()` takes the rest of the heading line with it.
        So the date may not change afterwards either: the tag holds a copy of it."""
        written = closed(self.FOLLOWED, "0.2.0", "2026-09-21")
        self.assertIn("## [0.2.0] - 2026-09-21\n\n### Added\n\n- X\n", written)
        self.assertTrue(sections(written)["0.2.0"].startswith("- 2026-09-21"))
        self.assertEqual(sections(written)["Unreleased"], "")

    def test_a_section_heading_is_read_as_commonmark_reads_one(self):
        """Indented up to three spaces, or with a tab after the #s, a section heading still starts a section.
        [Unreleased] is then still found and closed.
        Indented by four, it is a code block inside the section above."""
        log = "# Log\n\n  ## [Unreleased]\n\n### Added\n\n- X\n\n ##\t[0.1.0] - 2026-01-01\n\n- old\n"
        self.assertEqual(sections(log), {"Unreleased": "### Added\n\n- X", "0.1.0": "- 2026-01-01\n\n- old"})
        self.assertIn("## [0.2.0] - 2026-09-21\n\n### Added\n\n- X\n\n ##\t[0.1.0]", closed(log, "0.2.0", "2026-09-21"))
        self.assertEqual(list(sections(log.replace(" ##\t[0.1.0]", "    ## [0.1.0]"))), ["Unreleased"])

    def test_what_was_already_released_is_left_alone(self):
        written = closed(self.FOLLOWED, "0.2.0", "2026-09-21")
        self.assertIn("## [0.1.0] - 2026-01-01\n\n- old\n", written)
        self.assertIn("- X\n\n## [0.1.0]", written)  # The blank line between them is kept.

    def test_link_definitions_stay_at_the_foot_of_the_file(self):
        """Link definitions belong to the file, not to the section being closed.
        They are taken off the entries before the section is written, and put back below it,
        one blank line down however many blank lines stood above them.
        If they counted as entries, the blank lines after the last entry would stay inside the section."""
        written = closed(self.LINKED, "0.2.0", "2026-09-21")
        self.assertTrue(written.endswith("## [0.2.0] - 2026-09-21\n\n### Added\n\n- X\n\n"
                                         "[Unreleased]: https://example.invalid/x\n"))

    def test_closing_twice_is_refused_rather_than_burying_one(self):
        once = closed(self.FOLLOWED, "0.2.0", "2026-09-21")
        with self.assertRaises(SystemExit) as raised:
            closed(once, "0.2.0", "2026-09-22")
        # The reason matters. Closing an empty [Unreleased] is refused too, and if that were the only refusal,
        # a second close would get through where [Unreleased] still had entries.
        self.assertIn("already has a section", str(raised.exception))

    def test_a_release_with_nothing_to_say_is_refused(self):
        """An empty section is not a section.
        check_changelog would compare that emptiness against the tag forever, and the release notes would say
        nothing."""
        with self.assertRaises(SystemExit):
            closed("# Log\n\n## [Unreleased]\n\n## [0.1.0] - x\n\n- old\n", "0.2.0", "2026-09-21")

    def test_a_link_definition_is_not_something_to_release(self):
        """This input tells apart the two ways of deciding [Unreleased] is empty.
        With only a link definition under it, peeling off just blank lines would make a released section of it.
        `sections()` strips link definitions before comparing, so the mistake cannot be seen there.
        It has to be caught here."""
        with self.assertRaises(SystemExit) as raised:
            closed("# Log\n\n## [Unreleased]\n\n[Unreleased]: https://example.invalid/x\n", "0.2.0", "2026-09-21")
        self.assertIn("nothing is under [Unreleased]", str(raised.exception))

    def test_a_file_with_no_unreleased_section_is_refused(self):
        with self.assertRaises(SystemExit) as raised:
            closed("# Log\n\n## [0.1.0] - x\n\n- old\n", "0.2.0", "2026-09-21")
        self.assertIn("has no [Unreleased] section", str(raised.exception))

    def test_what_is_closed_is_what_check_changelog_then_holds(self):
        """The two halves have to agree: the section this writes is the one compared against the tag.
        So a tag taken of this text must find the section unchanged.

        Comparing a text with itself also passes when `sections()` cannot read the heading,
        since there is then no section on either side.
        So the section is first looked up by name, and the check is shown to fail on an edit:
        that is the half that proves it compares anything at all."""
        written = closed(self.FOLLOWED, "0.2.0", "2026-09-21")
        self.assertIn("0.2.0", sections(written))
        self.assertEqual(check_changelog(written, {"0.2.0": written}), [])
        self.assertNotEqual(check_changelog(written.replace("- X", "- Y"), {"0.2.0": written}), [])


class ClosingAPreReleaseTrain(unittest.TestCase):
    """A final release takes into its section the entries of every pre-release since the final release
    before it.
    The pre-releases' own sections stay as released.
    For a train that reached its own final release, this is what the Gradle changelog plugin's
    `combinePreReleases` does.
    That option is on by default there, so a changelog the plugin kept reads the same here.
    The plugin leaves an abandoned train out; this takes it in."""

    TRAIN = (
        "# Log\n\n## [Unreleased]\n\n### Fixed\n\n- F\n\n"
        "## [0.3.0-beta.2] - 2026-09-10\n\n### Added\n\n- B2\n\n"
        "## [0.3.0-beta.1] - 2026-09-05\n\n### Added\n\n- B1\n\n### Removed\n\n- R\n\n"
        "## [0.2.0] - 2026-09-01\n\n### Added\n\n- old\n"
    )

    def body(self, text, version):
        return check_release.bodies(text)[version]

    def test_a_final_release_takes_its_train_in_grouped_by_kind(self):
        """Kinds in Keep a Changelog's order, each kind once, entries in the order their sections come."""
        written = closed(self.TRAIN, "0.3.0", "2026-09-21")
        self.assertEqual(self.body(written, "0.3.0"),
                         "### Added\n\n- B2\n- B1\n\n### Removed\n\n- R\n\n### Fixed\n\n- F")

    def test_the_train_s_sections_stay_as_they_were_released(self):
        """This is safe beside check_changelog: nothing released is edited, only read."""
        written = closed(self.TRAIN, "0.3.0", "2026-09-21")
        self.assertEqual(check_changelog(written, {"0.3.0-beta.1": self.TRAIN, "0.3.0-beta.2": self.TRAIN}), [])

    def test_a_train_with_nothing_new_at_its_end_still_closes(self):
        """Emptiness is judged on the section that results, not on what stood under [Unreleased]."""
        quiet = self.TRAIN.replace("### Fixed\n\n- F\n\n", "")
        written = closed(quiet, "0.3.0", "2026-09-21")
        self.assertIn("- B1", self.body(written, "0.3.0"))

    def test_a_pre_release_takes_nothing_in(self):
        """Here this departs from the plugin's code and follows its documentation.
        A channel was offered beta.1 already; repeating it in beta.2's notes would tell them nothing."""
        written = closed(self.TRAIN.replace("0.3.0-beta.2", "0.3.0-beta.0"), "0.3.0-beta.2", "2026-09-21")
        self.assertEqual(self.body(written, "0.3.0-beta.2"), "### Fixed\n\n- F")

    def test_a_train_abandoned_for_another_version_is_taken_in_by_the_next_final_release(self):
        """0.3.0 never came, and 1.0.0 is the first final release since 0.2.0.
        Whoever skipped the betas is told what they brought, just as the link of 1.0.0 compares from 0.2.0."""
        written = closed(self.TRAIN, "1.0.0", "2026-09-21")
        self.assertEqual(self.body(written, "1.0.0"),
                         "### Added\n\n- B2\n- B1\n\n### Removed\n\n- R\n\n### Fixed\n\n- F")

    def test_a_hotfix_below_an_open_train_takes_none_of_it(self):
        written = closed(self.TRAIN, "0.2.1", "2026-09-21")
        self.assertEqual(self.body(written, "0.2.1"), "### Fixed\n\n- F")

    def test_a_pre_release_before_the_final_release_below_is_not_taken_in_again(self):
        """0.2.0 took in 0.2.0-beta.1 already."""
        earlier = self.TRAIN + "\n## [0.2.0-beta.1] - 2026-08-20\n\n### Added\n\n- older\n"
        written = closed(earlier, "0.3.0", "2026-09-21")
        self.assertEqual(self.body(written, "0.3.0"),
                         "### Added\n\n- B2\n- B1\n\n### Removed\n\n- R\n\n### Fixed\n\n- F")

    def test_a_first_final_release_takes_in_every_pre_release_below_it(self):
        first = "# Log\n\n## [Unreleased]\n\n## [0.1.0-beta.1] - 2026-08-20\n\n### Added\n\n- B\n"
        self.assertEqual(self.body(closed(first, "0.1.0", "2026-09-21"), "0.1.0"), "### Added\n\n- B")

    def test_nothing_new_and_no_train_is_still_refused(self):
        with self.assertRaises(SystemExit) as raised:
            closed(self.TRAIN.replace("### Fixed\n\n- F\n\n", ""), "0.2.1", "2026-09-21")
        self.assertIn("nothing is under [Unreleased]", str(raised.exception))

    def test_the_refusal_says_why_nothing_was_taken_in(self):
        """A pre-release takes nothing in, even where a train stands below it.
        So "no pre-release to take in" would be untrue of it, and the refusal says why instead.
        It would be untrue of a final release whose pre-releases say nothing, too."""
        quiet = self.TRAIN.replace("### Fixed\n\n- F\n\n", "")
        silent = "# Log\n\n## [Unreleased]\n\n## [0.3.0-beta.1] - x\n\n{}## [0.2.0] - x\n\n- old\n"
        untaken = ", and nothing in the pre-releases between 0.2.0 and 0.3.0 to take in"
        for changelog, version, said in (
                (quiet, "0.2.1", ", and no pre-release between 0.2.0 and 0.2.1 to take in"),
                (silent.format(""), "0.3.0", untaken),
                ("# Log\n\n## [Unreleased]\n", "0.1.0", ", and no pre-release below 0.1.0 to take in"),
                (quiet, "0.3.0-beta.3", ", and 0.3.0-beta.3, a pre-release, takes no other one in"),
                (quiet, "2026.10", "")):
            with self.subTest(version), self.assertRaises(SystemExit) as raised:
                closed(changelog, version, "2026-09-21")
            self.assertEqual(str(raised.exception),
                             f"nothing is under [Unreleased]{said}, so there is nothing to release")

    def test_a_group_of_another_name_is_kept_after_the_known_kinds(self):
        """Its text was released too; dropping it because it is not one of the six kinds would lose it."""
        odd = self.TRAIN.replace("### Removed\n\n- R", "### Notes\n\n- N")
        written = closed(odd, "0.3.0", "2026-09-21")
        self.assertTrue(self.body(written, "0.3.0").endswith("### Fixed\n\n- F\n\n### Notes\n\n- N"))


class TheLinksAtTheFoot(unittest.TestCase):
    """The link definitions are written the way the Gradle changelog plugin writes them,
    so a changelog it kept stays the same.
    Two cases differ: pre-releases among the sections, and a backport above a newer line.
    There each link compares from where its section's entries start."""

    def footer(self, *sections):
        text = "# Log\n\n## [Unreleased]\n\n" + "".join(f"## [{label}] - x\n\n- e\n\n" for label in sections)
        written = linked(text, "https://example.invalid/r", "v")
        return {line[1 : line.index("]")]: line.split("/r/", 1)[1] for line in written.splitlines()
                if line.startswith("[") and "]: " in line}

    def test_the_gradle_plugin_s_own_footer_is_reproduced(self):
        """Taken from a changelog that plugin wrote, with the prefix declared empty.
        Each comparison runs from the section below, and the oldest release links to its own commits."""
        text = ("# Log\n\n## [Unreleased]\n\n## [0.2.1] - 2026-09-19\n\n- f\n\n"
                "## [0.2.0] - 2026-09-15\n\n- a\n\n## [0.1.0] - 2026-09-13\n\n- b\n")
        repository_url = "https://github.com/loplex/intellij-maven-lens"
        self.assertTrue(linked(text, repository_url, "").endswith(
            "[Unreleased]: https://github.com/loplex/intellij-maven-lens/compare/0.2.1...HEAD\n"
            "[0.2.1]: https://github.com/loplex/intellij-maven-lens/compare/0.2.0...0.2.1\n"
            "[0.2.0]: https://github.com/loplex/intellij-maven-lens/compare/0.1.0...0.2.0\n"
            "[0.1.0]: https://github.com/loplex/intellij-maven-lens/commits/0.1.0\n"
        ))

    def test_a_final_release_is_compared_from_the_final_release_below_it(self):
        """Its section took in its train's entries, everything since 0.2.0, so its link shows everything since 0.2.0
        too.
        Compared from beta.2, it would leave out what beta.1 and beta.2 brought."""
        links = self.footer("0.3.0", "0.3.0-beta.2", "0.3.0-beta.1", "0.2.0")
        self.assertEqual(links["0.3.0"], "compare/v0.2.0...v0.3.0")
        self.assertEqual(links["0.3.0-beta.2"], "compare/v0.3.0-beta.1...v0.3.0-beta.2")
        self.assertEqual(links["0.3.0-beta.1"], "compare/v0.2.0...v0.3.0-beta.1")

    def test_a_pre_release_is_compared_from_its_own_train_past_a_hotfix(self):
        links = self.footer("0.3.0-beta.2", "0.2.1", "0.3.0-beta.1", "0.2.0")
        self.assertEqual(links["0.3.0-beta.2"], "compare/v0.3.0-beta.1...v0.3.0-beta.2")
        self.assertEqual(links["0.2.1"], "compare/v0.2.0...v0.2.1")

    def test_a_train_that_never_reached_its_final_release_is_passed_over_by_a_final_release_alone(self):
        """0.3.1's section took in 0.3.0-beta.1's entries, so its link shows everything since 0.2.0."""
        links = self.footer("0.4.0-beta.1", "0.3.1", "0.3.0-beta.1", "0.2.0")
        self.assertEqual(links["0.3.1"], "compare/v0.2.0...v0.3.1")
        self.assertEqual(links["0.4.0-beta.1"], "compare/v0.3.1...v0.4.0-beta.1")
        links = self.footer("0.4.0-beta.1", "0.3.0-beta.1", "0.2.0")
        self.assertEqual(links["0.4.0-beta.1"], "compare/v0.3.0-beta.1...v0.4.0-beta.1")

    def test_a_pre_release_after_a_train_s_final_release_is_compared_from_that_release(self):
        links = self.footer("0.3.0-beta.1", "0.2.0", "0.2.0-beta.1", "0.1.0")
        self.assertEqual(links["0.3.0-beta.1"], "compare/v0.2.0...v0.3.0-beta.1")

    def test_a_backport_is_not_what_a_newer_line_compares_from(self):
        links = self.footer("0.2.1", "0.1.3", "0.2.0", "0.1.2")
        self.assertEqual(links["0.2.1"], "compare/v0.2.0...v0.2.1")
        self.assertEqual(links["0.1.3"], "compare/v0.1.2...v0.1.3")

    def test_a_final_release_with_no_final_release_below_points_at_its_own_commits(self):
        links = self.footer("0.1.0", "0.1.0-beta.1")
        self.assertEqual(links["0.1.0"], "commits/v0.1.0")
        self.assertEqual(links["0.1.0-beta.1"], "commits/v0.1.0-beta.1")

    def test_a_label_that_is_not_semver_is_compared_from_the_section_below_it(self):
        links = self.footer("2026.10", "0.1.0-beta.1")
        self.assertEqual(links["2026.10"], "compare/v0.1.0-beta.1...v2026.10")

    def test_the_prefix_is_on_every_tag_and_nowhere_else(self):
        text = "# Log\n\n## [Unreleased]\n\n## [0.2.0] - x\n\n- a\n\n## [0.1.0] - x\n\n- b\n"
        written = linked(text, "https://example.invalid/r", "v")
        self.assertIn("[0.2.0]: https://example.invalid/r/compare/v0.1.0...v0.2.0\n", written)
        self.assertIn("[0.1.0]: https://example.invalid/r/commits/v0.1.0\n", written)
        self.assertIn("[Unreleased]: https://example.invalid/r/compare/v0.2.0...HEAD\n", written)

    def test_closing_writes_the_new_release_into_them(self):
        text = ("# Log\n\n## [Unreleased]\n\n- n\n\n## [0.1.0] - x\n\n- b\n\n"
                "[Unreleased]: https://example.invalid/r/compare/v0.1.0...HEAD\n")
        written = closed(text, "0.2.0", "2026-09-21", "https://example.invalid/r/", "v")
        self.assertIn("[Unreleased]: https://example.invalid/r/compare/v0.2.0...HEAD\n", written)
        self.assertIn("[0.2.0]: https://example.invalid/r/compare/v0.1.0...v0.2.0\n", written)
        self.assertEqual(written.count("[Unreleased]:"), 1, "the old definition is replaced, not kept beside")

    def test_a_definition_of_the_changelog_s_own_is_kept(self):
        text = ("# Log\n\nKept after [Keep a Changelog][kac].\n\n## [Unreleased]\n\n- n\n\n## [0.1.0] - x\n\n- b\n\n"
                "[kac]: https://keepachangelog.com/\n[0.1.0]: https://example.invalid/old\n")
        written = closed(text, "0.2.0", "2026-09-21", "https://example.invalid/r", "v")
        self.assertIn("[kac]: https://keepachangelog.com/\n", written)
        self.assertNotIn("https://example.invalid/old", written)

    def test_without_a_repository_url_the_footer_is_left_alone(self):
        text = "# Log\n\n## [Unreleased]\n\n- n\n\n[Unreleased]: https://example.invalid/custom\n"
        self.assertIn("[Unreleased]: https://example.invalid/custom\n", closed(text, "0.1.0", "2026-09-21"))


class TheReleaseNotes(unittest.TestCase):
    """One released section's text, printed for the release page.
    It comes from the file the changelog check holds to the tag, so the two cannot say different things.
    The one exception is the warning release-flow/warn puts above the notes while publishing elsewhere has not
    completed."""

    def notes_of(self, changelog, version):
        here = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (here / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
        original = check_release.REPO
        check_release.REPO = here
        self.addCleanup(setattr, check_release, "REPO", original)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            problems = check_release.notes_command(argparse.Namespace(version=version))
        return out.getvalue(), problems

    TEXT = ("# Log\n\n## [Unreleased]\n\n## [0.2.0] - 2026-09-21\n\n### Added\n\n- A\n\n"
            "## [0.1.0] - 2026-09-01\n\n- old\n\n[0.2.0]: https://example.invalid/x\n")

    def test_the_notes_are_the_section_without_its_heading(self):
        """No `## [0.2.0] - date` line: the release page has a title of its own, and the date would read as
        the first entry."""
        notes, problems = self.notes_of(self.TEXT, "0.2.0")
        self.assertEqual(problems, [])
        self.assertEqual(notes, "### Added\n\n- A\n")

    def test_link_definitions_are_not_notes(self):
        """Asked of the last section, because the definitions at the foot fall into its body.
        Any other section ends at the heading below it, so the definitions are outside it however it is read."""
        notes, _ = self.notes_of(self.TEXT, "0.1.0")
        self.assertNotIn("example.invalid", notes)

    def test_a_version_with_nothing_to_say_is_refused(self):
        _, problems = self.notes_of(self.TEXT.replace("### Added\n\n- A\n\n", ""), "0.2.0")
        self.assertTrue(problems)
        self.assertIn("holds nothing for 0.2.0", problems[0])

    def test_a_section_holding_only_spaces_is_refused_too(self):
        """Blank lines are taken off a body's ends, but spaces are not; a line of spaces is still nothing to say."""
        _, problems = self.notes_of(self.TEXT.replace("### Added\n\n- A\n", "   \n"), "0.2.0")
        self.assertTrue(problems)
        self.assertIn("holds nothing for 0.2.0", problems[0])

    def test_a_version_with_no_section_is_refused(self):
        _, problems = self.notes_of(self.TEXT, "0.3.0")
        self.assertTrue(problems)
        self.assertIn("holds nothing for 0.3.0", problems[0])


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

    def test_a_branch_that_still_holds_the_tag_is_named_with_both_readings(self):
        """Every release passes through this state, between being published and reaching the default branch.
        A squash or a rebase merge leaves the same state, and from the outside the two cannot be told apart:
        both replay the release commit, and the branch holding the original stays.
        Failing is right either way.
        Naming only the harmless reading would send the reader away from damage that is really there."""
        problems = check_ancestry({"0.2.0": False}, "v", {"0.2.0": "origin/release/0.2.0"})
        self.assertEqual(len(problems), 1)
        self.assertIn("origin/release/0.2.0", problems[0])
        self.assertIn("carried back", problems[0])
        self.assertIn("rebase", problems[0])

    def test_an_orphan_no_branch_holds_is_still_blamed_on_a_rewrite(self):
        """The two cases are told apart by whether any branch holds the tag.
        A tag left behind by a rebase merge whose branch was then deleted is the easiest to mistake for the other
        case, and it still reads as a rewrite."""
        problems = check_ancestry({"0.2.0": False}, "v", {"0.2.0": ""})
        self.assertEqual(len(problems), 1)
        self.assertIn("rewrite", problems[0])


class AskingTheRepository(unittest.TestCase):
    """What the checks over tags ask of git:
    - which releases this history reaches;
    - which branch holds a release it does not reach;
    - what `changelog` reports for a tag that holds no text to compare against.
    The first two exist for a release tagged on a branch this history has not taken in yet."""

    def setUp(self):
        self.here = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        original = check_release.REPO
        check_release.REPO = self.here
        self.addCleanup(setattr, check_release, "REPO", original)
        self.git("init", "-q", "-b", "main")
        self.commit("## [0.1.0] - 2026-01-01\n\n- A\n")
        self.git("tag", "v0.1.0")
        self.git("switch", "-q", "-c", "release/0.2.0")
        self.commit("## [0.2.0] - 2026-02-01\n\n- B\n\n## [0.1.0] - 2026-01-01\n\n- A\n")
        self.git("tag", "v0.2.0")
        self.git("branch", "aside")
        self.git("switch", "-q", "main")

    def git(self, *arguments: str) -> None:
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *arguments], cwd=self.here,
                       check=True, capture_output=True)

    def commit(self, below_title: str) -> None:
        (self.here / "CHANGELOG.md").write_text("# Changelog\n\n" + below_title, encoding="utf-8")
        self.git("add", "CHANGELOG.md")
        self.git("commit", "-q", "-m", "change")

    def test_only_a_release_off_this_history_is_unreachable(self):
        self.assertEqual(check_release.unreachable("v", ["0.1.0", "0.2.0"]), {"0.2.0"})

    def test_the_release_branch_is_named_ahead_of_another_holding_the_tag(self):
        """`aside` sorts first, so a holder that did not put the release branch first would name `aside`."""
        self.assertEqual(check_release.holder("v0.2.0", "0.2.0"), "release/0.2.0")

    def test_the_remote_s_branch_is_named_ahead_of_a_local_one(self):
        """A release is carried back from what the remote has.
        So the remote's branch is named, as fetched, even where a local branch of the same name holds the tag too."""
        self.git("update-ref", "refs/remotes/origin/release/0.2.0", "v0.2.0")
        self.assertEqual(check_release.holder("v0.2.0", "0.2.0"), "origin/release/0.2.0")

    def test_a_remote_branch_of_another_name_is_named_ahead_of_the_local_release_branch(self):
        """Once a remote branch holds the tag, only the remote's branches are sorted, whatever the remote is called.
        The local release branch is not pulled ahead of them."""
        self.git("update-ref", "refs/remotes/upstream/aside", "v0.2.0")
        self.assertEqual(check_release.holder("v0.2.0", "0.2.0"), "upstream/aside")

    def test_a_branch_merely_ending_in_the_release_branch_s_name_is_not_taken_for_it(self):
        """`prerelease/0.2.0` sorts before `release/0.2.0` and ends in its name.
        So only a whole component of a branch name counts as the release branch."""
        self.git("branch", "prerelease/0.2.0", "v0.2.0")
        self.assertEqual(check_release.holder("v0.2.0", "0.2.0"), "release/0.2.0")

    def test_a_section_off_this_history_is_not_called_deleted(self):
        with contextlib.redirect_stdout(io.StringIO()):
            problems = check_release.changelog_command(argparse.Namespace(version_source="tags", tag_prefix="v"))
        self.assertEqual(len(problems), 1)
        self.assertIn("not on this history", problems[0])

    def test_a_tag_older_than_its_section_is_reported_as_not_compared(self):
        """The report has to be honest about a section it could not compare.
        One whose tag holds no text of it is named as not compared, not counted among the sections that still
        read as released."""
        self.git("tag", "-d", "v0.2.0")
        self.git("tag", "v0.0.1")
        self.commit("## [0.1.0] - 2026-01-01\n\n- A\n\n## [0.0.1] - 2025-12-01\n\n- Z\n")
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            problems = check_release.changelog_command(argparse.Namespace(version_source="tags", tag_prefix="v"))
        self.assertEqual(problems, [])
        self.assertIn("Compared 1 released section(s)", printed.getvalue())
        self.assertIn("Not compared: 0.0.1 ", printed.getvalue())

    def test_a_tag_older_than_the_file_is_reported_as_not_compared(self):
        """A tag made before CHANGELOG.md existed has no text to compare against either.
        It is named the same way, not left out of the report."""
        self.git("tag", "-d", "v0.2.0")
        self.git("rm", "-q", "CHANGELOG.md")
        self.git("commit", "-q", "-m", "no changelog")
        self.git("tag", "v0.0.1")
        self.commit("## [0.1.0] - 2026-01-01\n\n- A\n\n## [0.0.1] - 2025-12-01\n\n- Z\n")
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            problems = check_release.changelog_command(argparse.Namespace(version_source="tags", tag_prefix="v"))
        self.assertEqual(problems, [])
        self.assertIn("Compared 1 released section(s)", printed.getvalue())
        self.assertIn("Not compared: 0.0.1 ", printed.getvalue())


class WritingTheVersionBack(unittest.TestCase):
    """`set-version` against a file on disk, where the line endings and the read-back matter."""

    def properties_file_holding(self, text: str) -> Path:
        here = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        (here / "gradle.properties").write_bytes(text.encode("utf-8"))
        original = check_release.REPO
        check_release.REPO = here
        self.addCleanup(setattr, check_release, "REPO", original)
        return here / "gradle.properties"

    def set_version(self, version: str) -> list[str]:
        with contextlib.redirect_stdout(io.StringIO()):
            return check_release.set_version_command(
                argparse.Namespace(version=version, version_source="gradle.properties", tag_prefix=None))

    def test_a_crlf_file_stays_crlf(self):
        """Read the way open() reads by default, every line would come back as LF.
        The release commit would then rewrite the whole file to change one line."""
        path = self.properties_file_holding("group=a\r\nversion=0.1.1-SNAPSHOT\r\ntagPrefix=v\r\n")
        self.assertEqual(self.set_version("0.1.1"), [])
        self.assertEqual(path.read_bytes(), b"group=a\r\nversion=0.1.1\r\ntagPrefix=v\r\n")

    def test_a_rewrite_that_did_not_take_is_caught_on_reading_back(self):
        """The read-back catches a writer and a reader that have come to disagree, which would otherwise fail
        silently.
        A writer that changes nothing stands in for that here."""
        self.properties_file_holding("version = 0.1.1-SNAPSHOT\n")
        with unittest.mock.patch.object(check_release.SOURCES["gradle.properties"], "with_version",
                                        lambda text, version: text):
            problems = self.set_version("0.1.1")
        self.assertTrue(problems)
        self.assertIn("still does not name 0.1.1", problems[0])

    def test_a_write_that_did_not_reach_the_file_is_caught_on_reading_back(self):
        """The other case the read-back is for: a rewrite that is right in memory but never reaches the file.
        A check over the rewritten text would pass it."""
        self.properties_file_holding("version = 0.1.1-SNAPSHOT\n")
        real_open = open

        def dropping_writes(file, mode="r", *arguments, **keywords):
            return io.StringIO() if "w" in mode else real_open(file, mode, *arguments, **keywords)

        with unittest.mock.patch.object(check_release, "open", dropping_writes, create=True):
            problems = self.set_version("0.1.1")
        self.assertTrue(problems)
        self.assertIn("still does not name 0.1.1", problems[0])

    def test_a_version_outside_latin_1_is_written_escaped_rather_than_breaking_the_file(self):
        """A character with no byte in the file's encoding would stop the write halfway, with the file already
        emptied.
        It is escaped instead, as Properties.store(OutputStream) escapes it, and reads back as it was given."""
        path = self.properties_file_holding("version = 0.1.1-SNAPSHOT\n")
        self.assertEqual(self.set_version("0.1.1-\u20ac"), [])
        self.assertEqual(path.read_bytes(), b"version = 0.1.1-\\u20AC\n")

    def test_a_lone_surrogate_in_the_version_leaves_the_file_as_it_was(self):
        """A lone surrogate handed to set_version_command directly is refused by stored().
        That happens before the file is opened for writing, so the file is left as it was, not emptied.
        From the command line, main() refuses it before it gets this far."""
        path = self.properties_file_holding("version = 0.1.1-SNAPSHOT\n")
        with self.assertRaises(UnicodeEncodeError):
            self.set_version("0.1.1-\udcff")
        self.assertEqual(path.read_bytes(), b"version = 0.1.1-SNAPSHOT\n")

    def test_a_comment_or_a_value_in_any_encoding_comes_back_in_its_own_bytes(self):
        """Gradle reads gradle.properties one byte to one character.
        So a comment in UTF-8, one in Latin-1, one holding every byte above ASCII, and a value in UTF-8
        are all as good as ASCII to it.
        A release leaves each of them exactly as it was."""
        path = self.properties_file_holding("")
        path.write_bytes("# sestaven\u00ed\n".encode("utf-8") + "# sestaven\u00ed\n".encode("iso-8859-1")
                         + b"# " + bytes(range(0x80, 0x100)) + b"\ndescription = " + "sestaven\u00ed".encode("utf-8")
                         + b"\nversion = 0.1.1-SNAPSHOT\n")
        before = path.read_bytes()
        self.assertEqual(self.set_version("0.1.1"), [])
        self.assertEqual(path.read_bytes(), before.replace(b"0.1.1-SNAPSHOT", b"0.1.1"))


class ReadingTheFile(unittest.TestCase):
    """The file a source names, read from disk in the encoding its format is read in."""

    def test_gradle_properties_is_read_a_byte_to_a_character_as_gradle_reads_it(self):
        """Gradle reads each byte of the file as the character with that code.
        So no byte above ASCII is decoded as UTF-8 or through another single-byte table.
        The prefix a release uses has to be the one the build sees."""
        here = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        (here / "gradle.properties").write_bytes(b"version = 0.1.1-SNAPSHOT\ntagPrefix = " + bytes(range(0x80, 0x100))
                                                 + b"\n")
        original = check_release.REPO
        check_release.REPO = here
        self.addCleanup(setattr, check_release, "REPO", original)
        self.assertEqual(check_release.prefix_from("gradle.properties", None), "".join(map(chr, range(0x80, 0x100))))


class WritingTheChangelogBack(unittest.TestCase):
    """`close-changelog` against a file; closed() itself is exercised over text above."""

    def changelog_file_holding(self, text: str) -> Path:
        here = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        (here / "CHANGELOG.md").write_bytes(text.encode("utf-8"))
        original = check_release.REPO
        check_release.REPO = here
        self.addCleanup(setattr, check_release, "REPO", original)
        return here / "CHANGELOG.md"

    def test_a_crlf_file_stays_crlf(self):
        """A CRLF file stays CRLF, for the same reason as in set-version:
        a release commit should change one section of the file, not every line of it."""
        path = self.changelog_file_holding("# Log\r\n\r\n## [Unreleased]\r\n\r\n### Added\r\n\r\n- A\r\n")
        with contextlib.redirect_stdout(io.StringIO()):
            problems = check_release.close_changelog_command(argparse.Namespace(
                version="0.1.0", date="2026-09-21", repository_url=None, version_source="tags", tag_prefix="v"))
        self.assertEqual(problems, [])
        self.assertEqual(path.read_bytes(),
                         b"# Log\r\n\r\n## [Unreleased]\r\n\r\n## [0.1.0] - 2026-09-21\r\n\r\n### Added\r\n\r\n- A\r\n")

    def test_a_file_of_lone_crs_stays_so(self):
        """A lone CR ends a line, as open() reads one by default, and the file keeps its lone CRs instead of coming
        back as LF."""
        path = self.changelog_file_holding("# Log\r\r## [Unreleased]\r\r### Added\r\r- A\r")
        with contextlib.redirect_stdout(io.StringIO()):
            problems = check_release.close_changelog_command(argparse.Namespace(
                version="0.1.0", date="2026-09-21", repository_url=None, version_source="tags", tag_prefix="v"))
        self.assertEqual(problems, [])
        self.assertEqual(path.read_bytes(),
                         b"# Log\r\r## [Unreleased]\r\r## [0.1.0] - 2026-09-21\r\r### Added\r\r- A\r")

    def test_a_refused_close_leaves_the_file_as_it_was(self):
        """A refusal is the rules saying no, and the changelog is still the one to fix, so it is left as it was."""
        text = "# Log\n\n## [Unreleased]\n\n## [0.1.0] - 2026-09-01\n\n- A\n"
        path = self.changelog_file_holding(text)
        with self.assertRaises(SystemExit):
            check_release.close_changelog_command(argparse.Namespace(
                version="0.2.0", date="2026-09-21", repository_url=None, version_source="tags", tag_prefix="v"))
        self.assertEqual(path.read_bytes(), text.encode("utf-8"))


class AVersionHandedIn(unittest.TestCase):
    """`--version` given in place of what the file declares, with or without the marker.
    Only a marker at the end of the version is taken off.
    A version carrying it anywhere else is still one being worked on."""

    def released_as(self, given):
        here = Path(self.enterContext(tempfile.TemporaryDirectory()))
        subprocess.run(["git", "init", "-q"], cwd=here, check=True)
        (here / "gradle.properties").write_text("version = 0.9.9-SNAPSHOT\ntagPrefix = v\n", encoding="utf-8")
        (here / "CHANGELOG.md").write_text("# Changelog\n\n## [Unreleased]\n", encoding="utf-8")
        original = check_release.REPO
        check_release.REPO = here
        self.addCleanup(setattr, check_release, "REPO", original)
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            problems = version_command(argparse.Namespace(version=given,
                                                          version_source="gradle.properties", tag_prefix="v"))
        return problems, printed.getvalue().strip()

    def test_a_version_handed_in_without_the_marker_is_released_as_it_is(self):
        self.assertEqual(self.released_as("0.2.0"), ([], "0.2.0"))

    def test_a_version_handed_in_with_the_marker_is_released_without_it(self):
        self.assertEqual(self.released_as("0.2.0-SNAPSHOT"), ([], "0.2.0"))

    def test_a_marker_that_does_not_end_the_version_is_not_taken_off(self):
        """`1.0.0-SNAPSHOT+b` is refused as what it is, a version being worked on."""
        problems, printed = self.released_as("1.0.0-SNAPSHOT+b")
        self.assertEqual((len(problems), printed), (1, ""))
        self.assertIn("1.0.0-SNAPSHOT+b is a version being worked on", problems[0])


class TheSourceAVersionComesFrom(unittest.TestCase):
    """The one thing a project type decides, which is two separate questions:
    - where the version is read from;
    - whether anything is written once it is released.
    A repository whose version lives only in its tags answers the first with "you tell me, or the one after
    the highest release, or a later one [Unreleased] asks for".
    It answers the second with "nowhere"."""

    def repository_with(self, *tags, declaring=None, changelog="# Changelog\n\n## [Unreleased]\n"):
        here = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        if changelog is not None:
            (here / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=here, check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                        "commit", "-q", "--allow-empty", "-m", "init"], cwd=here, check=True)
        for tag in tags:
            subprocess.run(["git", "tag", tag], cwd=here, check=True)
        if declaring is not None:
            (here / "gradle.properties").write_text(declaring, encoding="utf-8")
        original = check_release.REPO
        check_release.REPO = here
        self.addCleanup(setattr, check_release, "REPO", original)
        return here

    def problems_releasing(self, given, *tags, version_source="tags", prefix="v", **repository):
        # The command prints the version it accepted.
        # It is swallowed here, so that the suite's output holds only test results.
        self.repository_with(*tags, **repository)
        with contextlib.redirect_stdout(io.StringIO()):
            return version_command(argparse.Namespace(version=given, version_source=version_source, tag_prefix=prefix))

    def test_a_tag_source_releases_the_version_it_is_handed(self):
        self.repository_with("v0.1.0")
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            problems = version_command(argparse.Namespace(version="0.2.0", version_source="tags", tag_prefix="v"))
        self.assertEqual((problems, printed.getvalue().strip()), ([], "0.2.0"))

    def test_the_default_is_the_patch_after_the_highest_release(self):
        """A dispatch leaves the version field empty, rather than computing a default in its form.
        With nothing under [Unreleased] asking for more, the patch after the highest release comes back.
        Which release is the highest when their names sort differently is the next test's question."""
        self.repository_with("v0.1.0", "v0.2.0")
        self.assertEqual(next_candidate(check_release.released_versions("v")), "0.2.1")

    def test_the_default_is_measured_by_precedence_not_by_how_tags_sort(self):
        """`git tag -l` lists tags in ASCII order, where `v0.10.0` sorts before `v0.9.0`.
        Taking the last one listed would offer `0.9.1` as the version after `0.10.0`.
        The step check would then refuse a default this file produced."""
        self.repository_with("v0.9.0", "v0.10.0")
        self.assertEqual(next_candidate(check_release.released_versions("v")), "0.10.1")

    def test_an_open_train_is_defaulted_to_the_release_it_was_for(self):
        self.repository_with("v0.1.0", "v0.2.0-rc.1")
        self.assertEqual(next_candidate(check_release.released_versions("v")), "0.2.0")

    def test_the_default_moves_as_far_as_unreleased_asks(self):
        """Left empty, the version is the least one that what waits to be released allows:
        the minor after an addition, and from 1.0 on the major after a removal.
        That holds even where an open train would be followed by less."""
        self.repository_with("v0.2.0")
        releases = check_release.released_versions("v")
        self.assertEqual(next_candidate(releases, Asked(MINOR, "### Added", [], [])), "0.3.0")
        self.assertEqual(next_candidate(releases, Asked(MAJOR, "### Removed", [], [])), "0.3.0")
        self.repository_with("v1.2.0", "v1.3.0-beta.1")
        releases = check_release.released_versions("v")
        self.assertEqual(next_candidate(releases, Asked(MINOR, "### Added", [], [])), "1.3.0")
        self.assertEqual(next_candidate(releases, Asked(MAJOR, "### Removed", [], [])), "2.0.0")

    def test_version_reads_what_unreleased_asks(self):
        """End to end: the default a dispatch leaves empty, a version handed in, and a declared one."""
        added = "# Changelog\n\n## [Unreleased]\n\n### Added\n\n- A\n"
        self.repository_with("v0.2.0", changelog=added)
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            problems = version_command(argparse.Namespace(version=None, version_source="tags", tag_prefix="v"))
        self.assertEqual((problems, printed.getvalue().strip()), ([], "0.3.0"))
        self.assertIn("at least a minor, 0.3.0", " ".join(self.problems_releasing("0.2.1", "v0.2.0", changelog=added)))
        self.repository_with("v0.2.0", declaring="version = 0.2.1-SNAPSHOT\ntagPrefix = v\n", changelog=added)
        with contextlib.redirect_stdout(io.StringIO()):
            problems = version_command(argparse.Namespace(version=None,
                                                          version_source="gradle.properties", tag_prefix=None))
        self.assertIn("[Unreleased] holds ### Added", " ".join(problems))

    def test_a_hotfix_from_a_branch_carrying_an_open_train_is_held_to_it(self):
        """0.2.1 may go out while 0.3.0-beta.1 is open, from a branch the train has not reached.
        Cut from a branch whose changelog holds the beta's section, it would release the beta's addition as a
        patch."""
        on_the_train = ("# Changelog\n\n## [Unreleased]\n\n### Fixed\n\n- F\n\n## [0.3.0-beta.1] - 2026-09-20\n\n"
                        "### Added\n\n- A\n\n## [0.2.0] - 2026-09-01\n\n- old\n")
        self.assertEqual(self.problems_releasing("0.2.1", "v0.2.0", "v0.3.0-beta.1", changelog=on_the_train),
                         ["[0.3.0-beta.1] holds ### Added, so the release after 0.2.0 is at least a minor, 0.3.0, "
                          "and 0.2.1 is not"])
        self.assertEqual(self.problems_releasing("0.3.0", "v0.2.0", "v0.3.0-beta.1", changelog=on_the_train), [])
        off_the_train = "# Changelog\n\n## [Unreleased]\n\n### Fixed\n\n- F\n\n## [0.2.0] - 2026-09-01\n\n- old\n"
        self.assertEqual(self.problems_releasing("0.2.1", "v0.2.0", "v0.3.0-beta.1", changelog=off_the_train), [])

    def test_an_entry_under_no_group_is_refused_by_name(self):
        loose = "# Changelog\n\n## [Unreleased]\n\n- loose\n\n### Fixed\n\n- F\n"
        problems = self.problems_releasing("0.2.1", "v0.2.0", changelog=loose)
        self.assertEqual(problems, ["[Unreleased] has an entry under no ### group, so nothing says what kind of "
                                    "change it is: - loose"])

    def test_a_group_of_another_name_is_noted_and_passes(self):
        self.repository_with("v0.2.0", changelog="# Changelog\n\n## [Unreleased]\n\n### Documentation\n\n- D\n")
        said = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(said):
            problems = version_command(argparse.Namespace(version="0.2.1", version_source="tags", tag_prefix="v"))
        self.assertEqual(problems, [])
        self.assertIn("'### Documentation', which is not a kind of change Keep a Changelog names", said.getvalue())

    def test_a_changelog_without_an_unreleased_section_is_told_so(self):
        """`## Unreleased` without brackets is not the section Keep a Changelog writes, and what is under it is
        not read.
        That is said on stderr, not passed silently as a patch."""
        self.repository_with("v0.2.0", changelog="# Changelog\n\n## Unreleased\n\n### Added\n\n- A\n")
        said = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(said):
            problems = version_command(argparse.Namespace(version="0.2.1", version_source="tags", tag_prefix="v"))
        self.assertEqual(problems, [])
        self.assertIn("CHANGELOG.md has no [Unreleased] section", said.getvalue())

    def test_a_repository_without_a_changelog_is_told_so_and_asked_for_a_patch(self):
        self.repository_with("v0.2.0", changelog=None)
        said = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(said):
            problems = version_command(argparse.Namespace(version="0.2.1", version_source="tags", tag_prefix="v"))
        self.assertEqual(problems, [])
        self.assertIn("there is no CHANGELOG.md here", said.getvalue())

    def test_with_nothing_released_the_first_version_is_asked_for_rather_than_guessed(self):
        self.repository_with()
        with self.assertRaises(SystemExit) as raised:
            next_candidate(check_release.released_versions("v"))
        self.assertIn("say which version to release", str(raised.exception))

    def test_tags_that_are_no_release_are_noted_once(self):
        """version_command reads the tags once and hands them to next_candidate.
        So the note that none of them is a release is said once before the refusal, not once by each."""
        self.repository_with("deploy-1")
        said = io.StringIO()
        with contextlib.redirect_stderr(said), self.assertRaises(SystemExit) as raised:
            version_command(argparse.Namespace(version=None, version_source="tags", tag_prefix="v"))
        self.assertIn("say which version to release", str(raised.exception))
        self.assertEqual(said.getvalue().count("none of them is a release"), 1, said.getvalue())

    def test_a_tag_source_still_answers_to_the_rules(self):
        """The source decides where the candidate comes from, and nothing else.
        What may follow what is the same rule for every source."""
        problems = self.problems_releasing("0.4.0", "v0.1.0")
        self.assertTrue(problems)
        self.assertIn("does not follow 0.1.0", problems[0])

    def test_a_declaring_source_with_no_marker_releases_the_version_as_declared(self):
        """`marker_of` allows a source that declares a version without a marker.
        With an empty marker, the declared version has to come out whole, not as the empty string a slice to
        `-0` leaves.
        It has to be accepted, not refused as a version nobody would release."""
        self.repository_with("v0.1.0", declaring="version = 0.2.0\n")
        printed = io.StringIO()
        with unittest.mock.patch.object(check_release, "marker_of", lambda source: ""), \
                contextlib.redirect_stdout(printed):
            problems = version_command(argparse.Namespace(version=None,
                                                          version_source="gradle.properties", tag_prefix="v"))
        self.assertEqual(problems, [])
        self.assertEqual(printed.getvalue().strip(), "0.2.0")

    def test_the_commit_a_release_tags_passes_as_that_release(self):
        """Publishing a release creates its tag, and a workflow on push runs for that tag.
        The source there still names the version just released, and `version` is not being asked to release it
        again."""
        self.repository_with("v0.1.0", "v0.2.0", declaring="version = 0.2.0\ntagPrefix = v\n")
        printed, said = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(printed), contextlib.redirect_stderr(said):
            problems = version_command(argparse.Namespace(version=None,
                                                          version_source="gradle.properties", tag_prefix=None))
        self.assertEqual((problems, printed.getvalue().strip()), ([], "0.2.0"))
        self.assertIn("this commit is the release of 0.2.0", said.getvalue())

    def test_a_released_version_is_refused_on_a_commit_its_tag_is_not_on(self):
        here = self.repository_with("v0.2.0", declaring="version = 0.2.0\ntagPrefix = v\n")
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                        "commit", "-q", "--allow-empty", "-m", "after"], cwd=here, check=True)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            problems = version_command(argparse.Namespace(version=None,
                                                          version_source="gradle.properties", tag_prefix=None))
        self.assertTrue(problems)
        self.assertIn("released already", " ".join(problems))

    def test_a_released_version_handed_in_on_its_tagged_commit_is_still_refused(self):
        """A version given outright is a release being asked for, wherever it is asked."""
        self.repository_with("v0.2.0", declaring="version = 0.2.0\ntagPrefix = v\n")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            problems = version_command(argparse.Namespace(version="0.2.0",
                                                          version_source="gradle.properties", tag_prefix=None))
        self.assertIn("released already", " ".join(problems))

    def test_a_tag_source_declares_no_version_to_write(self):
        """`set-version` reporting success after writing nothing is the failure worth refusing:
        a release would carry on believing it had recorded a version.
        It is refused with a status of its own, so that a caller can tell it from a write that failed."""
        self.repository_with("v0.1.0")
        said = io.StringIO()
        with contextlib.redirect_stderr(said), self.assertRaises(SystemExit) as raised:
            check_release.set_version_command(argparse.Namespace(version="0.2.0",
                                                                 version_source="tags", tag_prefix="v"))
        self.assertEqual(raised.exception.code, check_release.NOTHING_TO_WRITE)
        self.assertNotIn(check_release.NOTHING_TO_WRITE, (1, 2), "the status of every other refusal, and argparse's")
        self.assertIn("declares no version", said.getvalue())

    def test_a_tag_source_declares_no_prefix_either(self):
        self.repository_with("v0.1.0")
        with self.assertRaises(SystemExit) as raised:
            prefix_from("tags", None)
        self.assertIn("--tag-prefix", str(raised.exception))

    def test_a_prefix_given_outright_is_taken_over_any_the_source_declares(self):
        self.repository_with(declaring="version = 1.0.0-SNAPSHOT\ntagPrefix = v\n")
        self.assertEqual(prefix_from("gradle.properties", ""), "")
        self.assertEqual(prefix_from("gradle.properties", "release-"), "release-")
        self.assertEqual(prefix_from("gradle.properties", None), "v")

    def test_a_declared_prefix_holding_a_lone_surrogate_is_refused(self):
        """The reader keeps an unpaired `\\uD83D`, as Java keeps it.
        Taken as a prefix, it made `prefix` end in a traceback while printing it.
        A pair is one character, and is accepted."""
        self.repository_with(declaring="version = 1.0.0-SNAPSHOT\ntagPrefix = \\uD83D\n")
        with self.assertRaises(SystemExit) as raised:
            prefix_from("gradle.properties", None)
        self.assertIn("tagPrefix in gradle.properties is '\\ud83d'", str(raised.exception))
        self.repository_with(declaring="version = 1.0.0-SNAPSHOT\ntagPrefix = \\uD83D\\uDE00\n")
        self.assertEqual(prefix_from("gradle.properties", None), "\U0001F600")


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
        repository = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                        "commit", "-q", "--allow-empty", "-m", "init"], cwd=repository, check=True)
        for tag in self.PLANTED:
            subprocess.run(["git", "tag", tag], cwd=repository, check=True)
        original = check_release.REPO
        check_release.REPO = repository
        self.addCleanup(setattr, check_release, "REPO", original)
        return sorted(check_release.released_versions(prefix))

    def test_a_v_prefix_takes_the_v_tags_and_hands_back_versions(self):
        self.assertEqual(self.releases_under("v"), ["0.1.0", "1.2.3-rc.1"])

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

    def test_a_tag_on_a_version_being_worked_on_is_not_a_release(self):
        """Somebody tagged a snapshot.
        Counting it would open a train on the channel `SNAPSHOT`, which every later pre-release would have to
        outrank."""
        self.assertNotIn("2.0.0-SNAPSHOT", self.releases_under("v"))

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
        original = check_release.REPO
        check_release.REPO = empty
        self.addCleanup(setattr, check_release, "REPO", original)
        said = io.StringIO()
        with contextlib.redirect_stderr(said):
            self.assertEqual(check_release.released_versions("v"), [])
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
        # contextlib.chdir would do, but it arrived in 3.11 and the suite runs on the 3.10 the actions ask for.
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(directory)

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

    def test_running_outside_a_repository_is_refused(self):
        nowhere = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.working_in(nowhere)
        with self.assertRaises(SystemExit):
            repository_root()


class ArgumentsThatAreNotText(unittest.TestCase):
    """A command-line byte that does not decode arrives as a lone surrogate (PEP 383).
    Nothing can print or write one.
    The tests run the script for real, with the bytes on the command line, because that is the only way one
    arrives."""

    def run_with(self, *arguments):
        here = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        subprocess.run(["git", "init", "-q"], cwd=here, check=True)
        files = {"gradle.properties": b"version = 0.1.1-SNAPSHOT\ntagPrefix = v\n",
                 "CHANGELOG.md": b"# Log\n\n## [Unreleased]\n\n- B\n\n## [0.1.0] - 2026-09-01\n\n- A\n"}
        for name, content in files.items():
            (here / name).write_bytes(content)
        done = subprocess.run([sys.executable, str(SCRIPT), *arguments], cwd=here, capture_output=True, text=True)
        self.assertEqual({name: (here / name).read_bytes() for name in files}, files, "a file was written")
        return done

    def test_each_is_refused_by_name_before_anything_is_written(self):
        """set-version used to end in a traceback, and close-changelog in one with CHANGELOG.md already emptied."""
        for arguments, named_in in (
                (["set-version", b"0.1.1-\xff"], "the version argument is '0.1.1-\\udcff'"),
                (["close-changelog", b"0.1.1-\xff"], "the version argument"),
                (["close-changelog", "--date", b"2026-09-\xff", "0.1.1"], "the date argument"),
                (["close-changelog", "--repository-url", b"https://example.com/\xff", "0.1.1"],
                 "the repository-url argument"),
                (["prefix", "--tag-prefix", b"\xff"], "the tag-prefix argument")):
            with self.subTest(named_in):
                done = self.run_with(arguments[0], "--version-source", "gradle.properties", *arguments[1:])
                self.assertEqual(done.returncode, 1)
                self.assertNotIn("Traceback", done.stderr)
                self.assertIn(named_in, done.stderr)


if __name__ == "__main__":
    unittest.main()
