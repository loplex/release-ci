#!/usr/bin/env python3
"""What a signature does to a zip, and what it leaves alone.

The archives here are built rather than described: a real zip, given bytes where a counter-signature puts
them - between the entry data and the central directory, with the offset pointing at the directory moved
along - so that what the comparison is held to is a file and not a belief about files.

Run with `python3 -m unittest discover` over the directory this file sits in.
"""

import subprocess
import sys
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path

PAYLOAD_PY = Path(__file__).resolve().parent / "publish" / "payload.py"

ENTRIES = {"META-INF/plugin.xml": b"<idea-plugin/>", "lib/plugin.jar": b"a jar, more or less" * 100}


class ThePayloadOfAnArchive(unittest.TestCase):
    def archive(self, entries=None, signing_block=b"", compression=zipfile.ZIP_DEFLATED):
        path = Path(self.enterContext(tempfile.TemporaryDirectory())) / "plugin.zip"
        with zipfile.ZipFile(path, "w", compression) as written:
            for name, data in (entries or ENTRIES).items():
                written.writestr(name, data)
        if signing_block:
            # Where a signing block goes: between the entry data and the central directory, with the one offset
            # pointing at the central directory, in the end record, moved along by as much.
            raw = path.read_bytes()
            end_record_at = raw.rindex(b"PK\x05\x06")
            directory_at = int.from_bytes(raw[end_record_at + 16 : end_record_at + 20], "little")
            path.write_bytes(raw[:directory_at] + signing_block + raw[directory_at : end_record_at + 16]
                             + (directory_at + len(signing_block)).to_bytes(4, "little") + raw[end_record_at + 20 :])
        return path

    def compare(self, accepted, served):
        return subprocess.run([sys.executable, str(PAYLOAD_PY), str(accepted), str(served)],
                              capture_output=True, text=True)

    def test_a_counter_signed_archive_carries_the_same_payload(self):
        """The case this exists for: the served file is not the accepted file and must still pass."""
        accepted = self.archive()
        served = self.archive(signing_block=b"a signature block")
        self.assertNotEqual(accepted.read_bytes(), served.read_bytes(), "the files have to differ")
        done = self.compare(accepted, served)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("2 entries, all matching", done.stdout)

    def test_recompressing_an_entry_is_not_a_difference(self):
        """Compressed size is not payload: the same bytes stored instead of deflated are the same entry."""
        done = self.compare(self.archive(), self.archive(compression=zipfile.ZIP_STORED))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_a_changed_entry_is_named(self):
        changed = dict(ENTRIES, **{"lib/plugin.jar": b"something else entirely"})
        done = self.compare(self.archive(), self.archive(changed))
        self.assertEqual(done.returncode, 1)
        self.assertIn("lib/plugin.jar differs", done.stderr)
        self.assertIn("accepted 1900B", done.stderr)

    def test_an_entry_rebuilt_to_the_same_length_is_caught(self):
        """What the CRC is there for, and the only shape size alone cannot see: as many bytes as before and
        not the same ones - a second build of the same source, or an entry somebody swapped."""
        same_length = dict(ENTRIES, **{"lib/plugin.jar": b"a JAR, more or less" * 100})
        self.assertEqual(len(same_length["lib/plugin.jar"]), len(ENTRIES["lib/plugin.jar"]))
        done = self.compare(self.archive(), self.archive(same_length))
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertRegex(done.stderr, r"lib/plugin\.jar differs: accepted 1900B/\w+, served 1900B/\w+")

    def test_an_entry_only_one_of_them_has_is_named_as_such(self):
        done = self.compare(self.archive(), self.archive(dict(ENTRIES, **{"lib/extra.jar": b"x"})))
        self.assertEqual(done.returncode, 1)
        self.assertIn("only the served archive has lib/extra.jar", done.stderr)
        done = self.compare(self.archive(dict(ENTRIES, **{"lib/extra.jar": b"x"})), self.archive())
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("only the accepted archive has lib/extra.jar", done.stderr)

    def test_an_entry_held_twice_is_not_the_same_as_once(self):
        path = Path(self.enterContext(tempfile.TemporaryDirectory())) / "twice.zip"
        with warnings.catch_warnings(), zipfile.ZipFile(path, "w") as written:
            warnings.simplefilter("ignore")  # zipfile warns of a duplicate name, which is the point here.
            for name, data in (*ENTRIES.items(), ("META-INF/plugin.xml", ENTRIES["META-INF/plugin.xml"])):
                written.writestr(name, data)
        done = self.compare(path, self.archive())
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("META-INF/plugin.xml is in the accepted archive 2 time(s) and in the served one 1",
                      done.stderr)

    def test_something_served_that_is_no_archive_is_said_not_to_be_one(self):
        page = Path(self.enterContext(tempfile.TemporaryDirectory())) / "served.zip"
        page.write_text("<html>not found, in a friendly way</html>", encoding="utf-8")
        done = self.compare(self.archive(), page)
        self.assertEqual(done.returncode, 1)
        self.assertIn("::error::what was compared is not a zip archive", done.stderr)
        self.assertNotIn("Traceback", done.stderr)

    def test_a_difference_is_said_to_be_one(self):
        done = self.compare(self.archive(), self.archive({"nothing.txt": b""}))
        self.assertIn("::error::the Marketplace is not serving the payload that was accepted", done.stderr)


if __name__ == "__main__":
    unittest.main()
