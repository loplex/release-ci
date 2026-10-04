"""Tests for rules/changelog.py: reading CHANGELOG.md's sections, closing `[Unreleased]`, and the links at its foot.

Run with `python3 -m unittest discover -s check-release` from the repository root.
"""

import unittest

from rules.changelog import bodies, check_changelog, closed, linked, sections, uncompared


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
        What the report does with that list is tested in TheChangelogCommand, in test_check_release.py."""
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
        return bodies(text)[version]

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
