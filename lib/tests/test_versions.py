"""Tests for rules/versions.py: which text is a version, how versions are ordered, which may follow which,
and the channel a version goes to.

Run with `python3 -m unittest discover -s lib` from the repository root.
"""

import unittest

from rules.versions import SEMVER, being_worked_on, channel_of, check_version, precedence, version_after


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
        lib/README.md quotes that rule.
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
