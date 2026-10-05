"""Tests for rules/steps.py: how far `[Unreleased]` and an open pre-release train ask the next version to move.

Run with `python3 -m unittest discover -s lib` from the repository root.
"""

import unittest

from rules.steps import Asked, MAJOR, MINOR, PATCH, asked_by, check_step, train_asks


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
