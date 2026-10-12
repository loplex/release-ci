#!/usr/bin/env python3
"""What stops the build:
- a Plugin Verifier that left no report;
- anything but exactly one signed archive where the build reports the archive to be;
- a signed archive whose plugin.xml is not the release's: its version, or the change notes the build was handed.

Run with `python3 -m unittest discover -s intellij` from the repository root, with the packages in
`lib/requirements.txt` installed.
"""

import io
import os
import re
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ARCHIVE_SH = Path(__file__).resolve().parent.parent / "build" / "archive.sh"
VERIFIER_REPORT_SH = ARCHIVE_SH.parent / "verifier-report.sh"
CHECK_ARCHIVE_PY = ARCHIVE_SH.parent / "check-archive.py"
CHANGE_NOTES_PY = ARCHIVE_SH.parent / "change-notes.py"
NOTES_SH = ARCHIVE_SH.parent / "notes.sh"
# The default `archive-pattern`, read from the action rather than copied, so that this test picks what the action picks.
DEFAULT_PATTERN = re.search(r"^  archive-pattern:\n(?:    .*\n)*?    default: (.+)$",
                            (ARCHIVE_SH.parent / "action.yml").read_text(encoding="utf-8"), re.MULTILINE).group(1)


def release_commit(work: Path, source: str = "gradle.properties", version: str = "1.2.0") -> None:
    """The commit intellij/build runs on: release-flow/prepare's, recording the source it wrote `version` into."""
    message = (f"chore(release): {version}\n\nRelease-CI-Version: {version}\nRelease-CI-Version-Source: {source}\n"
               "Release-CI-Tag-Prefix: v\n")
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m",
                    message], cwd=work, check=True)


class TheSignedArchive(unittest.TestCase):
    def setUp(self):
        self.work = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        (self.work / "build" / "distributions").mkdir(parents=True)

    def made(self, *names):
        for name in names:
            (self.work / "build" / "distributions" / name).write_bytes(b"an archive")

    def run_archive_sh(self, pattern=DEFAULT_PATTERN):
        written = self.work / "output.txt"
        written.write_text("", encoding="utf-8")
        done = subprocess.run(["bash", str(ARCHIVE_SH)], cwd=self.work, capture_output=True, text=True,
                              env={**os.environ, "ARCHIVE_PATTERN": pattern, "GITHUB_OUTPUT": str(written)})
        return done, written.read_text(encoding="utf-8")

    def test_the_one_signed_archive_is_named(self):
        self.made("plugin-1.0.0.zip", "plugin-1.0.0-signed.zip")
        done, output = self.run_archive_sh()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(output, "archive=build/distributions/plugin-1.0.0-signed.zip\n")

    def test_none_is_refused(self):
        done, output = self.run_archive_sh()
        self.assertEqual(done.returncode, 1)
        self.assertIn("matched 0 file(s)", done.stdout)
        self.assertEqual(output, "")

    def test_several_are_refused_rather_than_one_picked(self):
        self.made("a-signed.zip", "b-signed.zip")
        done, output = self.run_archive_sh()
        self.assertEqual(done.returncode, 1)
        self.assertIn("matched 2 file(s)", done.stdout)
        self.assertEqual(output, "")

    def test_a_path_naming_no_file_is_refused(self):
        """A path with no glob character comes back as itself, even though no file has that name."""
        done, output = self.run_archive_sh("build/distributions/plugin-signed.zip")
        self.assertEqual(done.returncode, 1)
        self.assertIn("names no file here", done.stdout)
        self.assertNotIn("matched 1 file(s)", done.stdout)
        self.assertEqual(output, "")

    def test_a_pattern_holding_a_space_is_one_pattern(self):
        """An archive named after a project called "My Plugin" is found whole, not split into two words."""
        self.made("My Plugin-1.0.0-signed.zip")
        done, output = self.run_archive_sh("build/distributions/My Plugin-*-signed.zip")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(output, "archive=build/distributions/My Plugin-1.0.0-signed.zip\n")


class TheVerifierReport(unittest.TestCase):
    def setUp(self):
        self.work = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.reports = self.work / "build" / "reports" / "pluginVerifier"

    def run_verifier_report_sh(self):
        return subprocess.run(["bash", str(VERIFIER_REPORT_SH)], cwd=self.work, capture_output=True, text=True)

    def test_a_build_that_left_a_report_goes_on(self):
        (self.reports / "IC-243.21565.193").mkdir(parents=True)
        (self.reports / "IC-243.21565.193" / "report.md").write_text("Compatible\n", encoding="utf-8")
        done = self.run_verifier_report_sh()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_a_build_that_left_no_report_stops(self):
        done = self.run_verifier_report_sh()
        self.assertEqual(done.returncode, 1)
        self.assertIn("left no report in build/reports/pluginVerifier", done.stdout)

    def test_an_empty_report_directory_is_no_report(self):
        """A Verifier that never ran can leave the directory behind, made by the build, with nothing in it."""
        self.reports.mkdir(parents=True)
        done = self.run_verifier_report_sh()
        self.assertEqual(done.returncode, 1)
        self.assertIn("left no report", done.stdout)


def jar(entries):
    """A jar's bytes, holding `entries` (name to text)."""
    held = io.BytesIO()
    with zipfile.ZipFile(held, "w") as written:
        for name, text in entries.items():
            written.writestr(name, text)
    return held.getvalue()


def plugin_xml(version, notes=None):
    """A plugin.xml as patchPluginXml writes one, with `notes` in a CDATA section as it writes change notes."""
    held = "" if notes is None else f"  <change-notes><![CDATA[{notes}]]></change-notes>\n"
    return f"<idea-plugin>\n  <id>x</id>\n{held}  <version>{version}</version>\n</idea-plugin>\n"


class TheArchiveCheck(unittest.TestCase):
    """The signed archive against gradle.properties, which release-flow/prepare wrote the release's version into."""

    def setUp(self):
        self.work = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        subprocess.run(["git", "init", "-q"], cwd=self.work, check=True)
        (self.work / "gradle.properties").write_text("version=1.2.0\ntagPrefix=v\n", encoding="utf-8")
        release_commit(self.work)
        self.archive = self.work / "plugin-1.2.0-signed.zip"

    def made(self, entries):
        """The signed archive, holding `entries` (name to bytes or text)."""
        with zipfile.ZipFile(self.archive, "w") as written:
            for name, data in entries.items():
                written.writestr(name, data)

    def plugin(self, version="1.2.0", notes=None):
        """A plugin as buildPlugin packs one: a directory with its jars under lib/, the plugin.xml in one of them."""
        self.made({"plugin/lib/plugin-1.2.0.jar": jar({"META-INF/plugin.xml": plugin_xml(version, notes)}),
                   "plugin/lib/library.jar": jar({"library/A.class": "a"})})

    def run_check(self, change_notes=None):
        env = {name: value for name, value in os.environ.items() if name != "CHANGE_NOTES"}
        if change_notes is not None:
            env["CHANGE_NOTES"] = change_notes
        return subprocess.run([sys.executable, str(CHECK_ARCHIVE_PY), str(self.archive)], cwd=self.work,
                              capture_output=True, text=True, env=env)

    def test_the_version_gradle_properties_names_passes(self):
        self.plugin()
        done = self.run_check()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("is version 1.2.0", done.stdout)

    def test_another_version_is_refused(self):
        """A build script that took its version from anywhere but the `version` line."""
        self.plugin("1.1.0")
        done = self.run_check()
        self.assertEqual(done.returncode, 1)
        self.assertIn("::error::plugin/lib/plugin-1.2.0.jar!/META-INF/plugin.xml says version 1.1.0, and "
                      "gradle.properties 1.2.0", done.stdout)

    def test_the_version_is_the_one_under_the_key_the_release_commit_records(self):
        """`version` holds what Gradle does with it; the release's version is in `appVersion`."""
        (self.work / "gradle.properties").write_text("version=9.9.9\nappVersion=1.2.0\ntagPrefix=v\n",
                                                     encoding="utf-8")
        release_commit(self.work, source="gradle.properties:appVersion")
        self.plugin()
        done = self.run_check()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("is version 1.2.0, as gradle.properties:appVersion says", done.stdout)
        self.plugin("9.9.9")
        done = self.run_check()
        self.assertEqual(done.returncode, 1)
        self.assertIn("says version 9.9.9, and gradle.properties:appVersion 1.2.0: the build script has to take the "
                      "plugin's version from the `appVersion` line", done.stdout)

    def test_a_commit_that_is_no_release_commit_is_refused(self):
        """Run anywhere but between release-flow/prepare and release-flow/draft, nothing says which line to read."""
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m",
                        "work"], cwd=self.work, check=True)
        self.plugin()
        done = self.run_check()
        self.assertEqual(done.returncode, 1)
        self.assertIn("::error::HEAD names a commit with no Release-CI-Version", done.stdout)

    def test_a_release_commit_recording_a_source_without_a_version_is_refused(self):
        """Under `tags` no file holds the release's version, so there is nothing to check the archive against."""
        release_commit(self.work, source="tags")
        self.plugin()
        done = self.run_check()
        self.assertEqual(done.returncode, 1)
        self.assertIn("the release commit records tags, which declares no version for the build to take", done.stdout)

    def test_a_plugin_xml_without_a_version_is_refused(self):
        self.made({"plugin/lib/plugin.jar": jar({"META-INF/plugin.xml": "<idea-plugin><id>x</id></idea-plugin>"})})
        done = self.run_check()
        self.assertEqual(done.returncode, 1)
        self.assertIn("plugin.xml has no <version>, and gradle.properties 1.2.0", done.stdout)

    def test_change_notes_outside_ascii_pass_under_an_ascii_locale(self):
        """check-archive.py restarts in UTF-8 mode (see main.in_utf8_mode): started outside it, it read CHANGE_NOTES
        in the locale's encoding, so notes outside ASCII never matched the plugin.xml they were built into."""
        self.plugin(notes="<p>café</p>")
        env = {**os.environ, "CHANGE_NOTES": "<p>café</p>",
               "LC_ALL": "C", "PYTHONCOERCECLOCALE": "0", "PYTHONUTF8": "0"}
        done = subprocess.run([sys.executable, str(CHECK_ARCHIVE_PY), str(self.archive)], cwd=self.work,
                              capture_output=True, env=env)
        self.assertEqual(done.returncode, 0, (done.stdout + done.stderr).decode("utf-8"))

    def test_a_plugin_that_is_one_jar_is_read_too(self):
        self.made({"META-INF/plugin.xml": plugin_xml("1.2.0")})
        done = self.run_check()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_no_plugin_xml_is_refused(self):
        self.made({"plugin/lib/library.jar": jar({"library/A.class": "a"})})
        done = self.run_check()
        self.assertEqual(done.returncode, 1)
        self.assertIn("0 jars under <name>/lib/ hold a META-INF/plugin.xml", done.stdout)

    def test_two_plugin_xmls_are_refused_rather_than_one_picked(self):
        self.made({"plugin/lib/a.jar": jar({"META-INF/plugin.xml": plugin_xml("1.2.0")}),
                   "plugin/lib/b.jar": jar({"META-INF/plugin.xml": plugin_xml("1.1.0")})})
        done = self.run_check()
        self.assertEqual(done.returncode, 1)
        self.assertIn("2 jars under <name>/lib/", done.stdout)

    def test_a_jar_outside_lib_is_not_read(self):
        """Only `<name>/lib/*.jar` is on the plugin's class path; a jar elsewhere in the archive is data."""
        self.made({"plugin/lib/plugin.jar": jar({"META-INF/plugin.xml": plugin_xml("1.2.0")}),
                   "plugin/samples/old.jar": jar({"META-INF/plugin.xml": plugin_xml("1.1.0")})})
        done = self.run_check()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    NOTES = "<h3>Fixed</h3>\n<ul>\n<li>a &amp; b</li>\n</ul>\n"

    def test_the_change_notes_the_build_was_handed_pass(self):
        """The build drops the last line break; white space at the ends is not compared."""
        self.plugin(notes=self.NOTES.rstrip("\n"))
        done = self.run_check(self.NOTES)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("with the change notes it was built with", done.stdout)

    def test_other_change_notes_are_refused(self):
        self.plugin(notes="<p>Rendered by the build script itself</p>")
        done = self.run_check(self.NOTES)
        self.assertEqual(done.returncode, 1)
        self.assertIn("holds other <change-notes> than the CHANGE_NOTES the build was handed", done.stdout)
        self.assertIn("the system has to have the C.UTF-8 locale Gradle runs in", done.stdout)

    def test_a_build_that_did_not_read_change_notes_is_refused(self):
        self.plugin()
        done = self.run_check(self.NOTES)
        self.assertEqual(done.returncode, 1)
        self.assertIn('has no <change-notes>, though the build was handed CHANGE_NOTES: the build script has to '
                      'set changeNotes = providers.environmentVariable("CHANGE_NOTES")', done.stdout)

    def test_without_change_notes_the_plugin_xml_s_own_are_left_alone(self):
        """change-notes off: a plugin that renders its own, or has none, is not asked about them."""
        self.plugin(notes="<p>Its own</p>")
        done = self.run_check()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertNotIn("change notes", done.stdout)

    def test_a_wrong_version_and_wrong_change_notes_are_both_named(self):
        self.plugin("1.1.0")
        done = self.run_check(self.NOTES)
        self.assertEqual(done.returncode, 1)
        self.assertIn("says version 1.1.0", done.stdout)
        self.assertIn("has no <change-notes>", done.stdout)

    def test_a_file_that_is_no_zip_is_refused(self):
        self.archive.write_bytes(b"an archive")
        done = self.run_check()
        self.assertEqual(done.returncode, 1)
        self.assertIn("::error::", done.stdout)
        self.assertNotIn("Traceback", done.stderr)


class TheChangeNotes(unittest.TestCase):
    """The section of CHANGELOG.md for the version in gradle.properties, rendered for the build."""

    def setUp(self):
        self.work = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        subprocess.run(["git", "init", "-q"], cwd=self.work, check=True)
        (self.work / "gradle.properties").write_text("version=1.2.0\n", encoding="utf-8")
        (self.work / "CHANGELOG.md").write_text("# Log\n\n## [Unreleased]\n\n## [1.2.0] - 2026-10-06\n\n### Fixed\n\n"
                                                "- A & B\n\n## [1.1.0] - 2026-10-01\n\n- Old\n", encoding="utf-8")
        release_commit(self.work)
        self.commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.work, check=True, capture_output=True,
                                     text=True).stdout.strip()

    def linked(self):
        """The section with a relative link and an image in it."""
        changelog = self.work / "CHANGELOG.md"
        changelog.write_text(changelog.read_text(encoding="utf-8").replace(
            "- A & B\n", "- A & B, see [the guide](docs/guide.md)\n- ![shot](docs/shot.png)\n"), encoding="utf-8")

    def run_change_notes_py(self, *arguments):
        return subprocess.run([sys.executable, str(CHANGE_NOTES_PY), *arguments], cwd=self.work, capture_output=True,
                              text=True)

    def run_notes_sh(self, tag="v1.2.0"):
        """notes.sh, and what it wrote to GITHUB_OUTPUT.
        The packages are not installed here: `PYTHON` stands for a Python that has them, and skips pip."""
        python = self.work / "python-stub"
        python.write_text(f'#!/usr/bin/env bash\n[[ $1 == -m ]] && exit 0\nexec "{sys.executable}" "$@"\n',
                          encoding="utf-8")
        python.chmod(0o755)
        output = self.work / "output.txt"
        output.write_text("", encoding="utf-8")
        done = subprocess.run(["bash", str(NOTES_SH)], cwd=self.work, capture_output=True, text=True,
                              env={**os.environ, "PYTHON": str(python), "RUNNER_TEMP": str(self.work),
                                   "GITHUB_OUTPUT": str(output), "REPOSITORY_URL": "https://github.com/o/r",
                                   "TAG": tag})
        return done, output.read_text(encoding="utf-8")

    def test_the_section_of_the_version_in_gradle_properties_as_html(self):
        done = self.run_change_notes_py("https://github.com/o/r", "v1.2.0")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout, "<h3>Fixed</h3>\n<ul>\n<li>A &amp; B</li>\n</ul>\n")

    def test_the_section_is_the_one_of_the_version_under_the_key_the_release_commit_records(self):
        """`version` holds what Gradle does with it, and CHANGELOG.md has no section for that."""
        (self.work / "gradle.properties").write_text("version=9.9.9\nappVersion=1.2.0\n", encoding="utf-8")
        release_commit(self.work, source="gradle.properties:appVersion")
        done = self.run_change_notes_py("https://github.com/o/r", "v1.2.0")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout, "<h3>Fixed</h3>\n<ul>\n<li>A &amp; B</li>\n</ul>\n")

    def test_notes_outside_ascii_are_printed_under_an_ascii_locale(self):
        """change-notes.py restarts in UTF-8 mode (see main.in_utf8_mode): started outside it, printing failed."""
        changelog = self.work / "CHANGELOG.md"
        changelog.write_text(changelog.read_text(encoding="utf-8").replace("- A & B\n", "- café\n"), encoding="utf-8")
        env = {**os.environ, "LC_ALL": "C", "PYTHONCOERCECLOCALE": "0", "PYTHONUTF8": "0"}
        done = subprocess.run([sys.executable, str(CHANGE_NOTES_PY), "https://github.com/o/r", "v1.2.0"],
                              cwd=self.work, capture_output=True, env=env)
        self.assertEqual(done.returncode, 0, done.stderr.decode("utf-8"))
        self.assertEqual(done.stdout.decode("utf-8"), "<h3>Fixed</h3>\n<ul>\n<li>café</li>\n</ul>\n")

    def test_a_relative_link_is_read_at_the_ref(self):
        self.linked()
        done = self.run_change_notes_py("https://github.com/o/r", "v1.2.0")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn('<a href="https://github.com/o/r/blob/v1.2.0/docs/guide.md">the guide</a>', done.stdout)
        self.assertIn('<img src="https://github.com/o/r/raw/v1.2.0/docs/shot.png" alt="shot" />', done.stdout)

    def test_a_page_holds_the_notes_and_says_where_its_links_lead(self):
        done = self.run_change_notes_py("https://github.com/o/r", "0123abc", "--page")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue(done.stdout.startswith('<!doctype html>\n<html lang="en">\n<meta charset="utf-8">\n'))
        self.assertIn("their relative links read at 0123abc", done.stdout)
        self.assertIn("<h3>Fixed</h3>\n<ul>\n<li>A &amp; B</li>\n</ul>\n</html>", done.stdout)

    def test_other_arguments_are_refused(self):
        for arguments in ((), ("https://github.com/o/r",), ("https://github.com/o/r", "v1.2.0", "--pages")):
            with self.subTest(arguments):
                done = self.run_change_notes_py(*arguments)
                self.assertNotEqual(done.returncode, 0)
                self.assertIn("usage: change-notes.py", done.stderr)

    def test_a_version_with_no_section_is_refused(self):
        (self.work / "gradle.properties").write_text("version=1.3.0\n", encoding="utf-8")
        for page in ((), ("--page",)):
            with self.subTest(page=page):
                done = self.run_change_notes_py("https://github.com/o/r", "v1.2.0", *page)
                self.assertEqual(done.returncode, 1)
                self.assertIn("holds nothing for 1.3.0", done.stderr)
                self.assertEqual(done.stdout, "")

    def test_notes_sh_writes_them_as_one_output(self):
        """An output of several lines, between delimiters the notes do not hold."""
        done, written = self.run_notes_sh()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        match = re.fullmatch(r"html<<(change-notes-[0-9a-f]{32})\n(.*)\n\1\npreview=(.*)\n", written, re.DOTALL)
        self.assertIsNotNone(match, written)
        self.assertEqual(match.group(2), "<h3>Fixed</h3>\n<ul>\n<li>A &amp; B</li>\n</ul>")
        self.assertEqual(Path(match.group(3)), self.work / "release-ci-change-notes-preview" / "change-notes.html")

    def test_notes_sh_reads_links_at_the_tag_and_the_page_at_the_commit(self):
        """The tag exists only once the draft is published; the commit checked out is pushed with the draft."""
        self.linked()
        done, written = self.run_notes_sh()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn('href="https://github.com/o/r/blob/v1.2.0/docs/guide.md"', written)
        page = Path(re.search(r"^preview=(.*)$", written, re.MULTILINE).group(1)).read_text(encoding="utf-8")
        self.assertIn(f'href="https://github.com/o/r/blob/{self.commit}/docs/guide.md"', page)
        self.assertIn(f'src="https://github.com/o/r/raw/{self.commit}/docs/shot.png"', page)

    def test_notes_sh_needs_the_tag(self):
        done, written = self.run_notes_sh(tag="")
        self.assertEqual(done.returncode, 1)
        self.assertIn("::error::intellij/build needs its tag input with change-notes: true", done.stdout)
        self.assertEqual(written, "")

    def test_notes_sh_shows_them_in_the_log_with_workflow_commands_stopped(self):
        """A line of the notes that starts with `::` is shown, not run as a workflow command."""
        changelog = self.work / "CHANGELOG.md"
        changelog.write_text(changelog.read_text(encoding="utf-8").replace("- A & B\n", "- A\n::error::B\n"),
                             encoding="utf-8")
        done, written = self.run_notes_sh()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        delimiter = re.match(r"html<<(\S+)\n", written).group(1)
        self.assertEqual(done.stdout.splitlines()[0], f"::stop-commands::{delimiter}")
        self.assertIn("\n::error::B</li>\n", done.stdout)
        self.assertEqual(done.stdout.splitlines()[-1], f"::{delimiter}::")

    def test_notes_sh_stops_on_a_refusal(self):
        (self.work / "gradle.properties").write_text("version=1.3.0\n", encoding="utf-8")
        done, written = self.run_notes_sh()
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(written, "")


if __name__ == "__main__":
    unittest.main()
