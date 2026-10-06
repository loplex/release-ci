#!/usr/bin/env python3
"""What stops the build:
- a Plugin Verifier that left no report;
- anything but exactly one signed archive where the build reports the archive to be;
- a signed archive whose plugin.xml is not the release's.

Run with `python3 -m unittest discover -s intellij` from the repository root.
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
# The default `archive-pattern`, read from the action rather than copied, so that this test picks what the action picks.
DEFAULT_PATTERN = re.search(r"^  archive-pattern:\n(?:    .*\n)*?    default: (.+)$",
                            (ARCHIVE_SH.parent / "action.yml").read_text(encoding="utf-8"), re.MULTILINE).group(1)


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


def plugin_xml(version):
    return f"<idea-plugin>\n  <id>x</id>\n  <version>{version}</version>\n</idea-plugin>\n"


class TheArchiveCheck(unittest.TestCase):
    """The signed archive against gradle.properties, which release-flow/prepare wrote the release's version into."""

    def setUp(self):
        self.work = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        subprocess.run(["git", "init", "-q"], cwd=self.work, check=True)
        (self.work / "gradle.properties").write_text("version=1.2.0\ntagPrefix=v\n", encoding="utf-8")
        self.archive = self.work / "plugin-1.2.0-signed.zip"

    def made(self, entries):
        """The signed archive, holding `entries` (name to bytes or text)."""
        with zipfile.ZipFile(self.archive, "w") as written:
            for name, data in entries.items():
                written.writestr(name, data)

    def plugin(self, version="1.2.0"):
        """A plugin as buildPlugin packs one: a directory with its jars under lib/, the plugin.xml in one of them."""
        self.made({"plugin/lib/plugin-1.2.0.jar": jar({"META-INF/plugin.xml": plugin_xml(version)}),
                   "plugin/lib/library.jar": jar({"library/A.class": "a"})})

    def run_check(self):
        return subprocess.run([sys.executable, str(CHECK_ARCHIVE_PY), str(self.archive)], cwd=self.work,
                              capture_output=True, text=True)

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

    def test_a_plugin_xml_without_a_version_is_refused(self):
        self.made({"plugin/lib/plugin.jar": jar({"META-INF/plugin.xml": "<idea-plugin><id>x</id></idea-plugin>"})})
        done = self.run_check()
        self.assertEqual(done.returncode, 1)
        self.assertIn("plugin.xml has no <version>, and gradle.properties 1.2.0", done.stdout)

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

    def test_a_file_that_is_no_zip_is_refused(self):
        self.archive.write_bytes(b"an archive")
        done = self.run_check()
        self.assertEqual(done.returncode, 1)
        self.assertIn("::error::", done.stdout)
        self.assertNotIn("Traceback", done.stderr)


if __name__ == "__main__":
    unittest.main()
