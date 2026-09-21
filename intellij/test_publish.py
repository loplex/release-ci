#!/usr/bin/env python3
"""What publish asks of the Marketplace, and what it does with the answers.

`curl` is a stub on PATH: it records what it was asked, answers the upload with a code the test chooses, and
answers the download with a code per attempt - so the waiting, the channel rule and the decision that the
upload's own answer does not settle the run are all exercised without a network. A download not told to
follow redirects is answered 301, as the Marketplace answers it.

Run with `python3 -m unittest discover` over the directory this file sits in.
"""

import os
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

PUBLISH = Path(__file__).resolve().parent / "publish" / "publish.sh"

CURL = r'''#!/bin/bash
printf '%s\n' "$*" >> "$STUBS/curl.log"
out=""; prev=""
for a in "$@"; do [ "$prev" = "-o" ] && out="$a"; prev="$a"; done
if [[ "$*" == *"/api/updates/upload"* ]]; then
  [ -n "$out" ] && printf 'the upload answer' > "$out"
  printf '%s' "$(cat "$STUBS/upload-code")"
  exit 0
fi
case " $* " in *" -L "*) ;; *) printf '301'; exit 0 ;; esac
code="$(head -1 "$STUBS/serve-codes")"; sed -i 1d "$STUBS/serve-codes"
[ "$code" = 200 ] && [ -n "$out" ] && cp "$STUBS/served.zip" "$out"
printf '%s' "$code"
'''


def archive(path, entries):
    with zipfile.ZipFile(path, "w") as written:
        for name, data in entries.items():
            written.writestr(name, data)
    return path


class Publish(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.stubs = root / "stubs"
        self.stubs.mkdir()
        # A runner always has one, and publish.sh writes its downloads into it.
        self.runner_temp = root / "runner-temp"
        self.runner_temp.mkdir()
        (self.stubs / "curl").write_text(CURL, encoding="utf-8")
        (self.stubs / "curl").chmod(0o755)
        # Notes how long it was asked to wait and returns at once, so that waiting is seen without being done.
        (self.stubs / "sleep").write_text(f'#!/bin/bash\nprintf "%s\\n" "$1" >> "{self.stubs}/slept"\n',
                                          encoding="utf-8")
        (self.stubs / "sleep").chmod(0o755)
        (self.stubs / "upload-code").write_text("200", encoding="utf-8")
        self.accepted = archive(root / "accepted.zip", {"META-INF/plugin.xml": b"<idea-plugin/>"})
        archive(self.stubs / "served.zip", {"META-INF/plugin.xml": b"<idea-plugin/>"})

    def serves(self, *codes):
        (self.stubs / "serve-codes").write_text("".join(f"{code}\n" for code in codes), encoding="utf-8")

    def publish(self, version="1.2.3", attempts=3, wait=0, plugin_id="cz.loplex.lens"):
        if not (self.stubs / "serve-codes").exists():
            self.serves(200)
        return subprocess.run(
            ["bash", str(PUBLISH)], capture_output=True, text=True,
            env={**os.environ, "PATH": f"{self.stubs}:{os.environ['PATH']}", "STUBS": str(self.stubs),
                 "PUBLISH_TOKEN": "a-publish-token", "PLUGIN_ID": plugin_id, "VERSION": version,
                 "ARCHIVE": str(self.accepted), "ATTEMPTS": str(attempts), "WAIT": str(wait),
                 "RUNNER_TEMP": str(self.runner_temp)},
        )

    def asked(self):
        return (self.stubs / "curl.log").read_text(encoding="utf-8").splitlines()

    def uploaded(self):
        return next(line for line in self.asked() if "/api/updates/upload" in line)

    def downloads(self):
        return [line for line in self.asked() if "/plugin/download" in line]

    def test_an_accepted_archive_that_is_served_back_passes(self):
        done = self.publish()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("all matching", done.stdout)

    def test_the_upload_being_refused_does_not_settle_the_run(self):
        """The decision this rests on: a version somebody uploaded by hand is served, and passes where
        it is the accepted archive, and a release is not failed for an answer that turned out not to
        matter."""
        (self.stubs / "upload-code").write_text("500", encoding="utf-8")
        done = self.publish()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("::warning::the upload was answered HTTP 500", done.stdout)
        self.assertEqual(len(self.downloads()), 1, "what is served is still asked for")

    def test_a_version_never_served_fails_after_the_attempts_given(self):
        self.serves(404, 404, 404, 404)
        done = self.publish(attempts=4)
        self.assertEqual(done.returncode, 1)
        self.assertEqual(len(self.downloads()), 4)
        self.assertIn("is not served by the Marketplace (last HTTP 404)", done.stdout + done.stderr)
        self.assertIn("The upload did not happen, or this plugin has no listing yet and the first version has to "
                      "be uploaded by hand", done.stdout + done.stderr)
        self.assertNotIn("review", done.stdout + done.stderr)

    def test_a_version_served_late_is_waited_for(self):
        """A version may be served a while after it is uploaded, so a 404 is asked again. Waited for, not only
        asked again: one wait of the length given, between the two attempts."""
        self.serves(404, 200)
        done = self.publish(attempts=3, wait=7)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(len(self.downloads()), 2)
        slept = self.stubs / "slept"
        self.assertEqual(slept.read_text(encoding="utf-8").split() if slept.exists() else [], ["7"])

    def test_the_last_attempt_is_not_waited_after(self):
        """The wait is between attempts: one after the last holds the run up for nothing before it fails."""
        self.serves(404, 404, 404)
        self.publish(attempts=3, wait=7)
        self.assertEqual((self.stubs / "slept").read_text(encoding="utf-8").split(), ["7", "7"])

    def test_what_is_served_is_held_to_the_payload_that_was_accepted(self):
        archive(self.stubs / "served.zip", {"META-INF/plugin.xml": b"<idea-plugin/>", "extra": b"x"})
        done = self.publish()
        self.assertEqual(done.returncode, 1)
        self.assertIn("only the served archive has extra", done.stderr)

    def test_a_final_release_names_no_channel_at_all(self):
        """`default` is what the Marketplace serves under no name; asking for it by that name is a 404. Build
        metadata with a hyphen in it, so that a rule spelled again as "a hyphen is a pre-release" is caught."""
        self.publish(version="1.2.3+build-7")
        self.assertNotIn("channel=", self.uploaded())
        self.assertNotIn("channel=", self.downloads()[0])

    def test_a_pre_release_is_uploaded_to_its_channel_and_asked_for_there(self):
        """The channel read off the version by check-release, the rule the draft was marked with."""
        self.publish(version="1.3.0-beta.1")
        self.assertRegex(self.uploaded(), r"-F channel=beta( |$)")
        self.assertTrue(self.downloads()[0].endswith("&channel=beta"), self.downloads()[0])

    def test_a_version_that_is_not_one_is_refused_before_anything_is_uploaded(self):
        done = self.publish(version="v1.2.3")
        self.assertEqual(done.returncode, 1)
        self.assertFalse((self.stubs / "curl.log").exists())

    def test_the_plugin_is_uploaded_under_its_id(self):
        self.publish(version="0.3.0-rc.1", plugin_id="org.example.plugin")
        self.assertRegex(self.uploaded(), r"-F xmlId=org\.example\.plugin( |$)")

    def test_the_token_goes_with_the_upload_and_nowhere_else(self):
        """The upload is refused without it. What is served back is public, and a secret sent where nothing
        needs it is one more place for it to leak from."""
        done = self.publish()
        self.assertIn("-H Authorization: Bearer a-publish-token ", self.uploaded())
        self.assertEqual(self.uploaded().count("a-publish-token"), 1, self.uploaded())
        self.assertNotIn("a-publish-token", "\n".join(self.downloads()))
        self.assertNotIn("a-publish-token", done.stdout + done.stderr)

    def test_the_plugin_is_asked_back_for_under_its_id(self):
        self.publish(version="0.3.0-rc.1", plugin_id="org.example.plugin")
        self.assertRegex(self.downloads()[0], r"[?&]pluginId=org\.example\.plugin(&|$)")

    def test_the_version_published_is_the_one_asked_back_for(self):
        """The upload carries no version of its own - that is inside the archive - so the version is held to
        what is asked back for."""
        self.publish(version="0.3.0-rc.1")
        self.assertRegex(self.downloads()[0], r"[?&]version=0\.3\.0-rc\.1(&|$)")

    def test_build_metadata_is_asked_back_for_encoded(self):
        """A `+` left bare in the query is read as a space, and the version asked for is then one never uploaded."""
        self.publish(version="0.3.0+build.5")
        self.assertIn("version=0.3.0%2Bbuild.5", self.downloads()[0])


if __name__ == "__main__":
    unittest.main()
