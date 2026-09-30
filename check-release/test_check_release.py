#!/usr/bin/env python3
"""The rules check-release.py holds: the rules themselves exercised without a repository to release, and
the helpers beside them that face git over one built for the purpose.

Run with `python3 -m unittest discover` over the directory this file sits in.
"""

import argparse
import contextlib
import importlib.util
import io
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
SEMVER = check_release.SEMVER


class Precedence(unittest.TestCase):
    def test_a_release_outranks_its_own_pre_releases(self):
        self.assertGreater(precedence("0.2.0"), precedence("0.2.0-rc.1"))

    def test_a_numeric_identifier_is_compared_as_a_number(self):
        self.assertLess(precedence("0.2.0-beta.9"), precedence("0.2.0-beta.10"))

    def test_a_numeric_identifier_ranks_below_an_alphanumeric_one(self):
        """The spec's rule, and one that can read backwards as text: `1.0.0-9` is an earlier step than
        `1.0.0-10a`, where `sorted` over the strings puts it after."""
        self.assertLess(precedence("1.0.0-9"), precedence("1.0.0-10a"))

    def test_build_metadata_does_not_figure_into_precedence(self):
        """The spec's requirement, quoted in the README beside this file: two versions differing only in build
        metadata have the same precedence. Ranking it instead would order releases by a field the spec says orders
        nothing."""
        self.assertEqual(precedence("1.0.0+a"), precedence("1.0.0+b"))
        self.assertEqual(precedence("1.0.0"), precedence("1.0.0+dfsg1"))
        self.assertLess(precedence("1.0.0-rc.1+z"), precedence("1.0.0+a"))

    def test_more_identifiers_outrank_fewer_when_the_ones_before_are_equal(self):
        self.assertLess(precedence("0.2.0-rc.1"), precedence("0.2.0-rc.1.1"))

    def test_the_numbers_come_before_the_suffix(self):
        self.assertLess(precedence("0.9.9"), precedence("1.0.0-rc.1"))


class WhatCountsAsAVersion(unittest.TestCase):
    """The grammar is SemVer 2.0.0's. Both halves are worth pinning: a shape the spec allows and this refused
    would be a release nobody could name, and a shape the spec leaves undefined and this took would be ordered
    here by rules nobody wrote down."""

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
        """The spec's own examples, plus the Debian-style repackage suffix. Metadata identifiers are looser
        than pre-release ones - a leading zero is allowed in them, because nothing counts them."""
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
    """The marker says the version has not been released, so a release is precisely what it cannot be. The
    rule is easiest to reach by accident: a script that appends -SNAPSHOT to a version already carrying it
    writes `1.0.0-SNAPSHOT-SNAPSHOT`, and the plain strip in `version` then offers `1.0.0-SNAPSHOT` up as the
    release."""

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
        """The equal half of the base invariant, where the step check has nothing to say: 0.2.0-rc.1 sits
        inside a core that 0.1.0 permits, so only `<=` stands between a tag and being released twice."""
        problems = check_version("0.2.0-rc.1", ["0.1.0", "0.2.0-rc.1"])
        self.assertEqual(len(problems), 1)
        self.assertIn("does not come after", problems[0])

    def test_going_backwards_inside_the_train_is_refused(self):
        self.assertTrue(check_version("0.2.0-rc.1", ["0.1.0", "0.2.0-rc.2"]))

    def test_a_stable_hotfix_may_go_out_while_a_train_is_open(self):
        """0.1.1 goes to everyone and only has to outrank the last release everyone was offered, 0.1.0. The
        subscribers who see 0.2.0-rc.1 are not offered a downgrade by it either: 0.1.1 sorts below the rc."""
        self.assertEqual(check_version("0.1.1", ["0.1.0", "0.2.0-rc.1"]), [])

    def test_a_hotfix_does_not_close_the_train(self):
        releases = ["0.1.0", "0.2.0-rc.1", "0.1.1"]
        self.assertEqual(check_version("0.2.0-rc.2", releases), [])
        self.assertEqual(check_version("0.2.0", releases), [])

    def test_a_pre_release_has_to_outrank_every_tag(self):
        """Subscribers to a channel see everything, so a pre-release below the highest tag is one they are never
        offered - which is what the base invariant refuses."""
        problems = check_version("0.1.2-rc.1", ["0.1.0", "0.1.1", "0.2.0-rc.1"])
        self.assertTrue(problems)
        self.assertIn("0.2.0-rc.1", problems[0])
        # In the order `git tag -l` lists them, by name: 0.10.0-rc.1 comes first and is still the highest.
        problems = check_version("0.9.2-rc.1", ["0.10.0-rc.1", "0.9.0", "0.9.1"])
        self.assertTrue(problems)
        self.assertIn("0.10.0-rc.1", problems[0])

    def test_a_hotfix_cannot_be_tried_on_a_channel_while_a_train_is_open(self):
        """The price of the rule above: 0.1.1 may go out, but 0.1.1-rc.1 sorts below 0.2.0-rc.1, so the hotfix
        cannot be offered to a channel first. Named here so that nobody finds it out from a red run."""
        problems = check_version("0.1.1-rc.1", ["0.1.0", "0.2.0-rc.1"])
        self.assertTrue(problems)
        self.assertIn("0.2.0-rc.1", problems[0])

    def test_with_nothing_final_released_the_open_train_is_the_only_way_on(self):
        """With nothing final released there is no step to take, so the open train is the whole of what may be
        worked towards. Left unmeasured, a project that has only ever tagged pre-releases could name any core
        at all - the step check reads the last final release, and there is none."""
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
        """The step is measured against the last final release, which an open train does not advance: past
        0.1.0 it is still one of 0.1.1, 0.2.0 and 1.0.0, and 0.3.0 is none of them."""
        problems = check_version("0.3.0", ["0.1.0", "0.2.0-rc.1"])
        self.assertTrue(problems)
        self.assertIn("does not follow 0.1.0", problems[0])
        self.assertEqual(check_version("1.0.0", ["0.1.0", "0.2.0-rc.1"]), [])


class TwoBuildsOfOneVersion(unittest.TestCase):
    """What taking build metadata costs. The spec leaves it out of ordering, so `1.0.0+b` does not outrank
    `1.0.0+a` - and a release nothing outranks is one no update check offers. Refused, and said in those words
    rather than as `does not come after`, which about a version that plainly came after reads as a bug."""

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
        """The neighbouring case, which is not a metadata question: nothing differs, so nothing has to be
        explained about ordering."""
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
        """`-SNAPSHOT` is Gradle's spelling of a version being worked on. A repository versioned by its tags
        has no such state, so what follows a release there is the bare version, which is also what `version`
        takes under `tags` when none is handed in."""
        self.assertEqual(self.next_after("v0.1.1", "gradle.properties"), ([], "0.1.2-SNAPSHOT"))
        self.assertEqual(self.next_after("v0.1.1", "tags"), ([], "0.1.2"))

    def next_after(self, released, source):
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            problems = check_release.next_command(argparse.Namespace(released=released, source=source,
                                                                     tag_prefix="v"))
        return problems, printed.getvalue().strip()

    def test_a_pre_release_goes_on_heading_for_the_release_it_was_for(self):
        """0.2.0-rc.1 was a step towards 0.2.0, so work carries on towards it. Counting the patch up here would
        skip the very release the train was running to, and the step check would refuse it afterwards."""
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
    """What the pre-release suffix is for. A project whose build names the channel too spells this rule a
    second time there, and the two then have to answer alike: what is uploaded and what is asked for afterwards
    have to be the same channel."""

    def test_a_final_release_goes_to_everyone(self):
        self.assertEqual(channel_of("0.3.0"), "default")

    def test_a_pre_release_goes_to_the_channel_its_suffix_names(self):
        self.assertEqual(channel_of("0.3.0-beta.1"), "beta")
        self.assertEqual(channel_of("1.0.0-rc.2"), "rc")
        self.assertEqual(channel_of("1.0.0-eap"), "eap")

    def test_a_hyphen_does_not_separate_identifiers(self):
        """`1.0.0-eap-2` and `1.0.0-eap.2` are both valid and do not mean the same thing here: the channel is
        the first dot-separated identifier, so the hyphenated spelling names a channel per build. Pinned so
        that nobody meets it as a build uploaded where nobody is subscribed."""
        self.assertEqual(channel_of("1.0.0-eap.2"), "eap")
        self.assertEqual(channel_of("1.0.0-eap-2"), "eap-2")

    def test_build_metadata_is_not_part_of_the_channel(self):
        self.assertEqual(channel_of("1.0.0+dfsg1"), "default")
        self.assertEqual(channel_of("0.3.0-beta.1+sha.5114f85"), "beta")
        # A pre-release with no dot before the `+`, and metadata carrying a hyphen: where the metadata is not
        # cut off first, the first reads `beta+sha` and the second names a channel of `7`.
        self.assertEqual(channel_of("0.3.0-beta+sha.5114f85"), "beta")
        self.assertEqual(channel_of("1.0.0+build-7"), "default")

    def test_the_version_being_worked_on_has_a_channel_by_the_same_rule(self):
        """Nothing carrying -SNAPSHOT is released - `version` refuses such a candidate and released_versions()
        leaves such a tag out - but the rule still has to answer what a second spelling of it would: with any
        `+` metadata off, everything after the first `-`, up to the first `.`, is the channel."""
        self.assertEqual(channel_of("0.2.1-SNAPSHOT"), "SNAPSHOT")

    def test_a_version_is_asked_about_with_or_without_the_tag_prefix(self):
        """What the argument's help promises: a tag's name is taken for the version it names, and a version
        handed in bare is taken as it is."""
        here = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        (here / "gradle.properties").write_text("tagPrefix = v\n", encoding="utf-8")
        original = check_release.REPO
        check_release.REPO = here
        self.addCleanup(setattr, check_release, "REPO", original)
        for version in ("v0.3.0-beta.1", "0.3.0-beta.1"):
            with self.subTest(version=version):
                printed = io.StringIO()
                with contextlib.redirect_stdout(printed):
                    problems = check_release.channel_command(
                        argparse.Namespace(version=version, source="gradle.properties", tag_prefix=None))
                self.assertEqual((problems, printed.getvalue()), ([], "beta\n"))


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
        """The hazard the check exists for: a three-way merge puts an entry that was added to [Unreleased] after
        the branch point into the released section instead, cleanly and without a conflict."""
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
        """uncompared() names every version whose tag holds no text of its section, and only those. What the
        report makes of that list is held in AskingTheRepository."""
        before = "# Changelog\n\n## [Unreleased]\n"
        later = self.AT_TAG.replace("[0.1.0]", "[0.2.0]")
        self.assertEqual(uncompared({"0.1.0": before, "0.2.0": later}), ["0.1.0"])
        self.assertEqual(uncompared({"0.1.0": self.AT_TAG}), [])

    def test_a_section_missing_while_its_release_is_off_this_history_is_not_called_deleted(self):
        """Between a release being published and its branch reaching the default branch, the section exists
        only where the tag does. `ancestry` already fails for it; this one saying the section is gone as well
        reads as a second, separate accusation about somebody having deleted text."""
        problems = check_changelog("# Changelog\n\n## [Unreleased]\n", {"0.1.0": self.AT_TAG}, {"0.1.0"})
        self.assertEqual(len(problems), 1)
        self.assertNotIn("is gone", problems[0])
        self.assertIn("has yet to reach here", problems[0])

    def test_a_section_missing_while_its_release_is_on_this_history_is_a_deletion(self):
        problems = check_changelog("# Changelog\n\n## [Unreleased]\n", {"0.1.0": self.AT_TAG}, set())
        self.assertEqual(len(problems), 1)
        self.assertIn("is gone", problems[0])


class ClosingTheUnreleasedSection(unittest.TestCase):
    """What a release does to the changelog before it is one, and the counterpart of check_changelog: what
    this writes is what the tag is about to hold a copy of, and what may never be edited again."""

    FOLLOWED = "# Log\n\n## [Unreleased]\n\n### Added\n\n- X\n\n## [0.1.0] - 2026-01-01\n\n- old\n"
    LINKED = "# Log\n\n## [Unreleased]\n\n### Added\n\n- X\n\n\n\n[Unreleased]: https://example.invalid/x\n"

    def test_the_entries_become_a_section_of_their_own(self):
        """The date stays part of the section, which is `sections()` taking the rest of the heading line in
        with it: it may not change afterwards either, the tag holding a copy of it."""
        written = closed(self.FOLLOWED, "0.2.0", "2026-09-21")
        self.assertIn("## [0.2.0] - 2026-09-21\n\n### Added\n\n- X\n", written)
        self.assertTrue(sections(written)["0.2.0"].startswith("- 2026-09-21"))
        self.assertEqual(sections(written)["Unreleased"], "")

    def test_what_was_already_released_is_left_alone(self):
        written = closed(self.FOLLOWED, "0.2.0", "2026-09-21")
        self.assertIn("## [0.1.0] - 2026-01-01\n\n- old\n", written)
        self.assertIn("- X\n\n## [0.1.0]", written)  # The blank line between them is not eaten.

    def test_link_definitions_stay_at_the_foot_of_the_file(self):
        """They belong to the file rather than to the section being closed, so they are taken off the entries
        before the section is written and put back below it, one blank line down however many stood above
        them. Taken as entries instead, they would keep the blank lines the entries ended in."""
        written = closed(self.LINKED, "0.2.0", "2026-09-21")
        self.assertTrue(written.endswith("## [0.2.0] - 2026-09-21\n\n### Added\n\n- X\n\n"
                                         "[Unreleased]: https://example.invalid/x\n"))

    def test_closing_twice_is_refused_rather_than_burying_one(self):
        once = closed(self.FOLLOWED, "0.2.0", "2026-09-21")
        with self.assertRaises(SystemExit) as raised:
            closed(once, "0.2.0", "2026-09-22")
        # Which refusal matters: closing an emptied [Unreleased] is refused too, and that reading would let
        # a second close through on a changelog that still had entries under it.
        self.assertIn("already has a section", str(raised.exception))

    def test_a_release_with_nothing_to_say_is_refused(self):
        """An empty section is not a section: check_changelog would compare that emptiness against the tag
        ever after, and nobody reading the release notes learns anything."""
        with self.assertRaises(SystemExit):
            closed("# Log\n\n## [Unreleased]\n\n## [0.1.0] - x\n\n- old\n", "0.2.0", "2026-09-21")

    def test_a_link_definition_is_not_something_to_release(self):
        """The one input that tells the two readings apart: with nothing but a link definition under
        [Unreleased], peeling only blank lines would make a released section out of it. `sections()` strips
        link definitions before comparing, so the mistake is invisible from there - it has to be caught here."""
        with self.assertRaises(SystemExit) as raised:
            closed("# Log\n\n## [Unreleased]\n\n[Unreleased]: https://example.invalid/x\n", "0.2.0", "2026-09-21")
        self.assertIn("nothing is under [Unreleased]", str(raised.exception))

    def test_a_file_with_no_unreleased_section_is_refused(self):
        with self.assertRaises(SystemExit) as raised:
            closed("# Log\n\n## [0.1.0] - x\n\n- old\n", "0.2.0", "2026-09-21")
        self.assertIn("has no [Unreleased] section", str(raised.exception))

    def test_what_is_closed_is_what_check_changelog_then_holds(self):
        """The two halves have to agree: the section this writes is the one compared against the tag, so a
        tag taken of this text must find it unchanged.

        Comparing the text with itself passes on a heading `sections()` cannot read, there being no section
        either side to compare - so the section is asked for by name first, and the check is made to fail on
        an edit, which is the half that says it compares anything at all."""
        written = closed(self.FOLLOWED, "0.2.0", "2026-09-21")
        self.assertIn("0.2.0", sections(written))
        self.assertEqual(check_changelog(written, {"0.2.0": written}), [])
        self.assertNotEqual(check_changelog(written.replace("- X", "- Y"), {"0.2.0": written}), [])


class ClosingAPreReleaseTrain(unittest.TestCase):
    """What the Gradle changelog plugin's `combinePreReleases` does, on by default there, so that a changelog
    that plugin kept reads the same here: a final release takes its train's entries into its own section, and
    the train's sections stay as released."""

    TRAIN = (
        "# Log\n\n## [Unreleased]\n\n### Fixed\n\n- F\n\n"
        "## [0.3.0-beta.2] - 2026-09-10\n\n### Added\n\n- B2\n\n"
        "## [0.3.0-beta.1] - 2026-09-05\n\n### Added\n\n- B1\n\n### Removed\n\n- R\n\n"
        "## [0.2.0] - 2026-09-01\n\n### Added\n\n- old\n"
    )

    def body(self, text, version):
        return check_release.bodies(text)[version]

    def test_a_final_release_takes_its_train_in_grouped_by_kind(self):
        """In Keep a Changelog's order of kinds, each kind once, entries in the order the sections come."""
        written = closed(self.TRAIN, "0.3.0", "2026-09-21")
        self.assertEqual(self.body(written, "0.3.0"),
                         "### Added\n\n- B2\n- B1\n\n### Removed\n\n- R\n\n### Fixed\n\n- F")

    def test_the_train_s_sections_stay_as_they_were_released(self):
        """What makes this safe beside check_changelog: nothing released is edited, only read."""
        written = closed(self.TRAIN, "0.3.0", "2026-09-21")
        self.assertEqual(check_changelog(written, {"0.3.0-beta.1": self.TRAIN, "0.3.0-beta.2": self.TRAIN}), [])

    def test_a_train_with_nothing_new_at_its_end_still_closes(self):
        """Emptiness is judged on the section that results, not on what stood under [Unreleased]."""
        quiet = self.TRAIN.replace("### Fixed\n\n- F\n\n", "")
        written = closed(quiet, "0.3.0", "2026-09-21")
        self.assertIn("- B1", self.body(written, "0.3.0"))

    def test_a_pre_release_takes_nothing_in(self):
        """Where this parts from the plugin's code and keeps to its documentation: a channel was offered
        beta.1 already, and beta.2's notes repeating it would tell them nothing."""
        written = closed(self.TRAIN.replace("0.3.0-beta.2", "0.3.0-beta.0"), "0.3.0-beta.2", "2026-09-21")
        self.assertEqual(self.body(written, "0.3.0-beta.2"), "### Fixed\n\n- F")

    def test_another_core_s_train_is_not_this_one(self):
        written = closed(self.TRAIN, "0.3.1", "2026-09-21")
        self.assertEqual(self.body(written, "0.3.1"), "### Fixed\n\n- F")

    def test_nothing_new_and_no_train_is_still_refused(self):
        with self.assertRaises(SystemExit) as raised:
            closed(self.TRAIN.replace("### Fixed\n\n- F\n\n", ""), "0.3.1", "2026-09-21")
        self.assertIn("nothing is under [Unreleased]", str(raised.exception))

    def test_a_group_of_another_name_is_kept_after_the_known_kinds(self):
        """Its text was released too; dropping it for not being one of the six would lose it."""
        odd = self.TRAIN.replace("### Removed\n\n- R", "### Notes\n\n- N")
        written = closed(odd, "0.3.0", "2026-09-21")
        self.assertTrue(self.body(written, "0.3.0").endswith("### Fixed\n\n- F\n\n### Notes\n\n- N"))


class TheLinksAtTheFoot(unittest.TestCase):
    """Written the way the Gradle changelog plugin writes them, so that a changelog it kept stays as it was."""

    def test_the_gradle_plugin_s_own_footer_is_reproduced(self):
        """Taken from a changelog that plugin wrote, with a prefix declared empty: the comparison runs from the
        section below, and the oldest release points at its own commits."""
        text = ("# Log\n\n## [Unreleased]\n\n## [0.2.1] - 2026-09-19\n\n- f\n\n"
                "## [0.2.0] - 2026-09-15\n\n- a\n\n## [0.1.0] - 2026-09-13\n\n- b\n")
        repository_url = "https://github.com/loplex/intellij-maven-lens"
        self.assertTrue(linked(text, repository_url, "").endswith(
            "[Unreleased]: https://github.com/loplex/intellij-maven-lens/compare/0.2.1...HEAD\n"
            "[0.2.1]: https://github.com/loplex/intellij-maven-lens/compare/0.2.0...0.2.1\n"
            "[0.2.0]: https://github.com/loplex/intellij-maven-lens/compare/0.1.0...0.2.0\n"
            "[0.1.0]: https://github.com/loplex/intellij-maven-lens/commits/0.1.0\n"
        ))

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
    """One released section's text, printed for the release page, from the file the changelog check holds to
    the tag - so the two cannot come to say different things, but for the warning release-flow/warn puts above
    the notes while publishing the release elsewhere has not completed."""

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
        """Asked of the last section, which is the one whose body the definitions at the foot fall into. Any
        other section ends at the heading below it, so the definitions are outside it however it is read, and
        the question goes unasked."""
        notes, _ = self.notes_of(self.TEXT, "0.1.0")
        self.assertNotIn("example.invalid", notes)

    def test_a_version_with_nothing_to_say_is_refused(self):
        _, problems = self.notes_of(self.TEXT.replace("### Added\n\n- A\n\n", ""), "0.2.0")
        self.assertTrue(problems)
        self.assertIn("holds nothing for 0.2.0", problems[0])

    def test_a_section_holding_only_spaces_is_refused_too(self):
        """Blank lines are taken off a body's ends, but spaces are not: a line of them is still nothing to
        say."""
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
        """What a squash merge, a rebase merge, GitHub's `Update with rebase` or a force-push all do to the
        release commit. The check asks after the property rather than after the cause, so it holds for a way of
        rewriting a branch that nobody has thought of yet."""
        problems = check_ancestry({"0.1.0": True, "0.2.0": False}, "v")
        self.assertEqual(len(problems), 1)
        self.assertIn("v0.2.0", problems[0])

    def test_an_orphan_is_named_the_way_this_repository_tags(self):
        """Both spellings are in use, `v0.2.0` and a bare `0.2.0`, and a report that names a tag nobody can look up
        is a report that sends its reader to the wrong place - whether a branch still holds the tag or not."""
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
        """The state every release passes through between being published and reaching the default branch -
        and, indistinguishably from the outside, what a squash or a rebase merge leaves behind, since both
        replay the release commit and leave the branch that holds the original standing. Failing is right
        either way; naming only the innocent reading sends the reader away from damage that is there."""
        problems = check_ancestry({"0.2.0": False}, "v", {"0.2.0": "origin/release/0.2.0"})
        self.assertEqual(len(problems), 1)
        self.assertIn("origin/release/0.2.0", problems[0])
        self.assertIn("carried back", problems[0])
        self.assertIn("rebase", problems[0])

    def test_an_orphan_no_branch_holds_is_still_blamed_on_a_rewrite(self):
        """Told apart by whether any branch holds the tag, so a tag that a rebase merge left behind while its
        branch was deleted - the shape that is easiest to mistake for the other - still reads as a rewrite."""
        problems = check_ancestry({"0.2.0": False}, "v", {"0.2.0": ""})
        self.assertEqual(len(problems), 1)
        self.assertIn("rewrite", problems[0])


class AskingTheRepository(unittest.TestCase):
    """What the checks over tags ask of Git: which releases this history reaches, which branch holds one it
    does not, and what `changelog` reports of a tag that holds no text to compare against. A release tagged on a
    branch the history has not taken in is the case the first two exist for."""

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
        """`aside` sorts first, so a holder that did not put the release branch ahead would name it."""
        self.assertEqual(check_release.holder("v0.2.0", "0.2.0"), "release/0.2.0")

    def test_the_remote_s_branch_is_named_ahead_of_a_local_one(self):
        """A release is carried back from what the remote has, so the branch named is the remote's, as it is
        fetched, even where a local branch of the same name holds the tag as well."""
        self.git("update-ref", "refs/remotes/origin/release/0.2.0", "v0.2.0")
        self.assertEqual(check_release.holder("v0.2.0", "0.2.0"), "origin/release/0.2.0")

    def test_a_remote_branch_of_another_name_is_named_ahead_of_the_local_release_branch(self):
        """Once a remote branch holds the tag, only the remote's branches are sorted, whatever the remote is
        called: the local release branch is not pulled ahead of them."""
        self.git("update-ref", "refs/remotes/upstream/aside", "v0.2.0")
        self.assertEqual(check_release.holder("v0.2.0", "0.2.0"), "upstream/aside")

    def test_a_branch_merely_ending_in_the_release_branch_s_name_is_not_taken_for_it(self):
        """`prerelease/0.2.0` sorts ahead of `release/0.2.0` and ends in its name, so only a whole component
        of a branch's name is taken for the release branch."""
        self.git("branch", "prerelease/0.2.0", "v0.2.0")
        self.assertEqual(check_release.holder("v0.2.0", "0.2.0"), "release/0.2.0")

    def test_a_section_off_this_history_is_not_called_deleted(self):
        with contextlib.redirect_stdout(io.StringIO()):
            problems = check_release.changelog_command(argparse.Namespace(source="tags", tag_prefix="v"))
        self.assertEqual(len(problems), 1)
        self.assertIn("not on this history", problems[0])

    def test_a_tag_older_than_its_section_is_reported_as_not_compared(self):
        """The report has to be honest about a section it could not compare: one whose tag holds no text of it
        is named as not compared, rather than counted among the sections that still read as released."""
        self.git("tag", "-d", "v0.2.0")
        self.git("tag", "v0.0.1")
        self.commit("## [0.1.0] - 2026-01-01\n\n- A\n\n## [0.0.1] - 2025-12-01\n\n- Z\n")
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            problems = check_release.changelog_command(argparse.Namespace(source="tags", tag_prefix="v"))
        self.assertEqual(problems, [])
        self.assertIn("Compared 1 released section(s)", printed.getvalue())
        self.assertIn("Not compared: 0.0.1 ", printed.getvalue())

    def test_a_tag_older_than_the_file_is_reported_as_not_compared(self):
        """A tag made before CHANGELOG.md existed holds no text to compare against either, and is named the
        same way rather than left out of the report."""
        self.git("tag", "-d", "v0.2.0")
        self.git("rm", "-q", "CHANGELOG.md")
        self.git("commit", "-q", "-m", "no changelog")
        self.git("tag", "v0.0.1")
        self.commit("## [0.1.0] - 2026-01-01\n\n- A\n\n## [0.0.1] - 2025-12-01\n\n- Z\n")
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            problems = check_release.changelog_command(argparse.Namespace(source="tags", tag_prefix="v"))
        self.assertEqual(problems, [])
        self.assertIn("Compared 1 released section(s)", printed.getvalue())
        self.assertIn("Not compared: 0.0.1 ", printed.getvalue())


class WritingTheVersionBack(unittest.TestCase):
    """`set-version` against a file, which is where the read-back lives."""

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
                argparse.Namespace(version=version, source="gradle.properties", tag_prefix=None))

    def test_a_rewrite_that_did_not_take_is_caught_on_reading_back(self):
        """The read-back is what catches a writer and a reader that have come to disagree, which is the quiet
        failure; a writer that changes nothing stands in for one here."""
        self.properties_file_holding("version = 0.1.1-SNAPSHOT\n")
        with unittest.mock.patch.object(check_release.SOURCES["gradle.properties"], "with_version",
                                        lambda text, version: text):
            problems = self.set_version("0.1.1")
        self.assertTrue(problems)
        self.assertIn("still does not name 0.1.1", problems[0])

    def test_a_write_that_did_not_reach_the_file_is_caught_on_reading_back(self):
        """The other half of what the read-back is for: a rewrite that is right in memory and never reaches the
        file, which a check over the rewritten text would pass."""
        self.properties_file_holding("version = 0.1.1-SNAPSHOT\n")
        real_open = open

        def dropping_writes(file, mode="r", *arguments, **keywords):
            return io.StringIO() if "w" in mode else real_open(file, mode, *arguments, **keywords)

        with unittest.mock.patch.object(check_release, "open", dropping_writes, create=True):
            problems = self.set_version("0.1.1")
        self.assertTrue(problems)
        self.assertIn("still does not name 0.1.1", problems[0])

    def test_a_version_outside_latin_1_is_written_escaped_rather_than_breaking_the_file(self):
        """A character the file's encoding has no byte for would stop the write halfway, with the file already
        emptied; escaped as Properties.store(OutputStream) escapes it, it is written, and read back as it was given."""
        path = self.properties_file_holding("version = 0.1.1-SNAPSHOT\n")
        self.assertEqual(self.set_version("0.1.1-\u20ac"), [])
        self.assertEqual(path.read_bytes(), b"version = 0.1.1-\\u20AC\n")

    def test_a_lone_surrogate_in_the_version_leaves_the_file_as_it_was(self):
        """A command-line byte that Python's filesystem encoding cannot decode reaches the version as a lone surrogate,
        which stored() refuses to encode before the file is opened for writing: the file is left as it was, not
        emptied."""
        path = self.properties_file_holding("version = 0.1.1-SNAPSHOT\n")
        with self.assertRaises(UnicodeEncodeError):
            self.set_version("0.1.1-\udcff")
        self.assertEqual(path.read_bytes(), b"version = 0.1.1-SNAPSHOT\n")

    def test_a_comment_or_a_value_in_any_encoding_comes_back_in_its_own_bytes(self):
        """Gradle reads gradle.properties a byte to a character, so a comment saved in UTF-8, one saved in Latin-1,
        one holding every byte above ASCII and a value saved in UTF-8 are all as good as ASCII to it, and a release
        leaves each of them exactly as it was."""
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
        """Gradle reads every byte of the file as the one character with that code, so no byte above ASCII is
        decoded as part of UTF-8 or through another single-byte table: the prefix a release takes has to be the one
        the build sees."""
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

    def test_a_refused_close_leaves_the_file_as_it_was(self):
        """A refusal is the rules saying no, and the changelog they said it about is still the one to fix."""
        text = "# Log\n\n## [Unreleased]\n\n## [0.1.0] - 2026-09-01\n\n- A\n"
        path = self.changelog_file_holding(text)
        with self.assertRaises(SystemExit):
            check_release.close_changelog_command(argparse.Namespace(
                version="0.2.0", date="2026-09-21", repository_url=None, source="tags", tag_prefix="v"))
        self.assertEqual(path.read_bytes(), text.encode("utf-8"))


class AVersionHandedIn(unittest.TestCase):
    """`--version` in place of what the file declares, spelled with the marker or without it. Only a marker
    ending the version comes off, so a version carrying it anywhere else is still one being worked on."""

    def released_as(self, given):
        here = Path(self.enterContext(tempfile.TemporaryDirectory()))
        subprocess.run(["git", "init", "-q"], cwd=here, check=True)
        (here / "gradle.properties").write_text("version = 0.9.9-SNAPSHOT\ntagPrefix = v\n", encoding="utf-8")
        original = check_release.REPO
        check_release.REPO = here
        self.addCleanup(setattr, check_release, "REPO", original)
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            problems = version_command(argparse.Namespace(version=given, source="gradle.properties", tag_prefix="v"))
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
    """The one thing a project type decides. The two halves are not the same question: where the version is
    read from, and whether anything is written once it is released. A repository whose version lives only in
    its tags answers the first with "you tell me, or the one after the highest release" and the second with
    "nowhere"."""

    def repository_with(self, *tags, declaring=None):
        here = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
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

    def problems_releasing(self, given, *tags, source="tags", prefix="v"):
        # The command prints the candidate it accepted; swallowed here so that a suite's output holds test
        # results and nothing else.
        self.repository_with(*tags)
        with contextlib.redirect_stdout(io.StringIO()):
            return version_command(argparse.Namespace(version=given, source=source, tag_prefix=prefix))

    def test_a_tag_source_releases_the_version_it_is_handed(self):
        self.repository_with("v0.1.0")
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            problems = version_command(argparse.Namespace(version="0.2.0", source="tags", tag_prefix="v"))
        self.assertEqual((problems, printed.getvalue().strip()), ([], "0.2.0"))

    def test_the_default_is_the_patch_after_the_highest_release(self):
        """What a dispatch leaves to this rather than computing in a form: the field is empty, and the patch
        after the highest release is what comes back. Which release is the highest where their names sort
        otherwise is the next test's."""
        self.repository_with("v0.1.0", "v0.2.0")
        self.assertEqual(next_candidate("v"), "0.2.1")

    def test_the_default_is_measured_by_precedence_not_by_how_tags_sort(self):
        """`git tag -l` hands them back in ASCII order, where `v0.10.0` sorts before `v0.9.0`. Taking the last
        one listed would offer `0.9.1` as the version after `0.10.0` - a release the step check then refuses,
        from a default this file produced."""
        self.repository_with("v0.9.0", "v0.10.0")
        self.assertEqual(next_candidate("v"), "0.10.1")

    def test_an_open_train_is_defaulted_to_the_release_it_was_for(self):
        self.repository_with("v0.1.0", "v0.2.0-rc.1")
        self.assertEqual(next_candidate("v"), "0.2.0")

    def test_with_nothing_released_the_first_version_is_asked_for_rather_than_guessed(self):
        self.repository_with()
        with self.assertRaises(SystemExit) as raised:
            next_candidate("v")
        self.assertIn("say which version to release", str(raised.exception))

    def test_a_tag_source_still_answers_to_the_rules(self):
        """The adapter decides where the candidate comes from and nothing else: what may follow what is the
        same rule for every source."""
        problems = self.problems_releasing("0.4.0", "v0.1.0")
        self.assertTrue(problems)
        self.assertIn("does not follow 0.1.0", problems[0])

    def test_a_declaring_source_with_no_marker_releases_the_version_as_declared(self):
        """`marker_of` allows for a source that declares a version and carries no marker on it. Read off with
        an empty marker, the declared version has to come out whole - not as the empty string a slice to `-0`
        leaves - and be accepted, not refused as a version nobody would release."""
        self.repository_with("v0.1.0", declaring="version = 0.2.0\n")
        printed = io.StringIO()
        with unittest.mock.patch.object(check_release, "marker_of", lambda source: ""), \
                contextlib.redirect_stdout(printed):
            problems = version_command(argparse.Namespace(version=None, source="gradle.properties", tag_prefix="v"))
        self.assertEqual(problems, [])
        self.assertEqual(printed.getvalue().strip(), "0.2.0")

    def test_the_commit_a_release_tags_passes_as_that_release(self):
        """Publishing a release creates its tag, and a workflow on push runs for it: the source there still names
        the version just released, and `version` is not being asked to release it again."""
        self.repository_with("v0.1.0", "v0.2.0", declaring="version = 0.2.0\ntagPrefix = v\n")
        printed, said = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(printed), contextlib.redirect_stderr(said):
            problems = version_command(argparse.Namespace(version=None, source="gradle.properties", tag_prefix=None))
        self.assertEqual((problems, printed.getvalue().strip()), ([], "0.2.0"))
        self.assertIn("this commit is the release of 0.2.0", said.getvalue())

    def test_a_released_version_is_refused_on_a_commit_its_tag_is_not_on(self):
        here = self.repository_with("v0.2.0", declaring="version = 0.2.0\ntagPrefix = v\n")
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                        "commit", "-q", "--allow-empty", "-m", "after"], cwd=here, check=True)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            problems = version_command(argparse.Namespace(version=None, source="gradle.properties", tag_prefix=None))
        self.assertTrue(problems)
        self.assertIn("released already", " ".join(problems))

    def test_a_released_version_handed_in_on_its_tagged_commit_is_still_refused(self):
        """Handed in, a version is a release being asked for, wherever it is asked."""
        self.repository_with("v0.2.0", declaring="version = 0.2.0\ntagPrefix = v\n")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            problems = version_command(argparse.Namespace(version="0.2.0", source="gradle.properties", tag_prefix=None))
        self.assertIn("released already", " ".join(problems))

    def test_a_tag_source_declares_no_version_to_write(self):
        """`set-version` reporting success having written nothing is the failure worth refusing: a release
        would carry on believing it had recorded something. Refused with a status of its own, so that a caller
        can tell it from a write that failed."""
        self.repository_with("v0.1.0")
        said = io.StringIO()
        with contextlib.redirect_stderr(said), self.assertRaises(SystemExit) as raised:
            check_release.set_version_command(argparse.Namespace(version="0.2.0", source="tags", tag_prefix="v"))
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


class WhichTagsCountAsReleases(unittest.TestCase):
    """A repository carries tags that are not releases - another component's, a deployment's - and it carries
    its releases under whichever spelling it tags with. Two things sort that out, and the tests below hold
    both: the prefix, which is what a project tagging `v*` selects by and strips, and the version pattern,
    which is what keeps `v0.1.0` out of a project that tags bare versions - selecting by what the tag starts
    with passes it and the prefix takes nothing off it, so only the pattern refuses it. Getting the prefix
    wrong passes, because what it produces is an empty list and a check that passes having compared nothing,
    with a note on stderr at most; getting the pattern wrong passes too, a tag of another kind counted as a
    release, with no note at all."""

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
        """`10.1.0` is what tells the two apart. Selecting by what the tag starts with leaves it out of a `v`
        repository; taking the prefix off whatever is listed would turn it into `0.1.0` - a version, and a
        second one, silently colliding with the release actually tagged `v0.1.0`."""
        self.assertEqual(self.releases_under("v").count("0.1.0"), 1)

    def test_what_is_not_a_version_is_not_a_release_under_either(self):
        """`v1.2` has two numbers and `version-1.0` merely starts with the letter. What each would have to be
        called to slip through depends on the prefix: under `v` it is what the tag leaves once the prefix is
        taken off, and under none it is the tag itself."""
        for prefix, two_numbers, merely_starts in (("v", "1.2", "ersion-1.0"), ("", "v1.2", "version-1.0")):
            with self.subTest(prefix=prefix):
                found = self.releases_under(prefix)
                self.assertNotIn(two_numbers, found)
                self.assertNotIn(merely_starts, found)

    def test_a_tag_on_a_version_being_worked_on_is_not_a_release(self):
        """Somebody tagged a snapshot. Counting it would open a train on the channel `SNAPSHOT` that every
        later pre-release has to outrank."""
        self.assertNotIn("2.0.0-SNAPSHOT", self.releases_under("v"))

    def test_counting_none_out_of_many_is_said_out_loud(self):
        """What a prefix nobody checked looks like from the outside, and the shape every check then passes on
        having compared nothing, bar a `version` under `tags` that has no release to count from. Said rather
        than failed: a repository may carry tags of other kinds only."""
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
        """A first release has nothing to be consistent with, which is not the same as having looked in the
        wrong place for it."""
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
        """It could come back two ways: whole, where nothing asks whether the tag is a version, and as the
        version it ends in, where whatever stands in front of that is taken off. Each is refused apart."""
        for prefix in ("v", ""):
            with self.subTest(prefix=prefix):
                found = self.releases_under(prefix)
                self.assertTrue(set(found).isdisjoint({"api/v9.9.9", "deploy/1.0.0", "milestone-2026-09"}),
                                found)
                self.assertTrue(set(found).isdisjoint({"9.9.9", "1.0.0"}), found)


class WhichRepositoryIsBeingChecked(unittest.TestCase):
    """Not the one this file lives in. Run from a checkout of its own repository against another, a root
    taken from the script's own path would name that checkout instead - and quietly so, because it carries a
    CHANGELOG.md of its own for the checks to read."""

    def test_the_root_is_the_repository_the_run_is_in(self):
        elsewhere = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        subprocess.run(["git", "init", "-q"], cwd=elsewhere, check=True)
        self.enterContext(contextlib.chdir(elsewhere))
        self.assertEqual(repository_root(), elsewhere)
        (elsewhere / "sub").mkdir()
        with contextlib.chdir(elsewhere / "sub"):
            self.assertEqual(repository_root(), elsewhere, "the root, not the directory the run is in")

    def test_help_answers_outside_a_repository(self):
        """The repository is resolved when a subcommand first reads it, not when the file is loaded: nobody
        asking what the subcommands are should have to stand inside a repository to be told."""
        nowhere = Path(self.enterContext(tempfile.TemporaryDirectory()))
        done = subprocess.run([sys.executable, str(SCRIPT), "--help"], cwd=nowhere, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("set-version", done.stdout)

    def test_a_subcommand_that_reads_the_repository_still_refuses_outside_one(self):
        nowhere = Path(self.enterContext(tempfile.TemporaryDirectory()))
        done = subprocess.run([sys.executable, str(SCRIPT), "--source", "gradle.properties", "prefix"],
                              cwd=nowhere, capture_output=True, text=True)
        self.assertEqual(done.returncode, 1)
        self.assertIn("inside the repository", done.stderr)

    def test_a_repository_missing_a_file_it_is_read_from_is_told_which(self):
        """A traceback is the wrong kind of loud: it reads as the tool breaking and names no file to add."""
        empty = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        subprocess.run(["git", "init", "-q"], cwd=empty, check=True)
        for command, missing in (("prefix", "gradle.properties"), ("changelog", "CHANGELOG.md")):
            with self.subTest(command=command):
                done = subprocess.run([sys.executable, str(SCRIPT), "--source", "gradle.properties", command],
                                      cwd=empty, capture_output=True, text=True)
                self.assertEqual(done.returncode, 1)
                self.assertNotIn("Traceback", done.stderr)
                self.assertIn(f"there is no {missing} here", done.stderr)

    def test_running_outside_a_repository_is_refused(self):
        nowhere = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(contextlib.chdir(nowhere))
        with self.assertRaises(SystemExit):
            repository_root()


if __name__ == "__main__":
    unittest.main()
