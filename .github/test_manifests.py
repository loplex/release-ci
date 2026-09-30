#!/usr/bin/env python3
"""What every action.yml this repository tracks has to be true of, read as text.

Run with `python3 -m unittest discover -s .github` from the repository's root, with the packages in
`.github/requirements.txt` installed.
"""

import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFESTS = sorted(subprocess.run(["git", "ls-files", "-z", "--", "*/action.yml"], cwd=ROOT, check=True,
                                  capture_output=True, text=True).stdout.split("\0")[:-1])

# The inputs each action marks `required: true`, which every workflow that uses it has to pass.
REQUIRED = {
    "check-release/action.yml": {"source"},
    "intellij/build/action.yml": {"certificate-chain", "private-key", "private-key-password"},
    "intellij/publish/action.yml": {"plugin-id", "version", "archive", "token"},
    "release-flow/draft/action.yml": {"source", "version", "tag", "branch"},
    "release-flow/merge-back/action.yml": {"source", "tag", "default-branch", "check-workflow"},
    "release-flow/prepare/action.yml": {"source"},
    "release-flow/warn/action.yml": {"tag", "outcome", "to"},
}


def required(manifest):
    """The inputs a manifest marks `required: true`; a `required:` holding anything but `true` or `false` fails."""
    inputs = re.search(r"^inputs:\n((?:\n|[ #].*\n)*)", (ROOT / manifest).read_text(encoding="utf-8"), re.MULTILINE)
    names, name = set(), None
    for line in inputs.group(1).splitlines() if inputs else ():
        if key := re.fullmatch(r"  ([\w-]+):\s*", line):
            name = key.group(1)
        elif flag := re.fullmatch(r"    required:\s*(.*?)\s*", line):
            if flag.group(1) not in ("true", "false"):
                raise ValueError(f"{manifest}: input {name}: required: {flag.group(1)}")
            if flag.group(1) == "true":
                names.add(name)
    return names


class Manifests(unittest.TestCase):

    def test_an_expression_stands_only_as_a_value(self):
        """GitHub evaluates `${{ }}` wherever it stands in action.yml, a description's text included, and one it
        cannot evaluate there fails every step that uses the action before anything runs. In a `run:` script it
        would be pasted into the code, which is why inputs reach the scripts through `env:`."""
        self.assertTrue(MANIFESTS)
        for manifest in MANIFESTS:
            for number, line in enumerate((ROOT / manifest).read_text(encoding="utf-8").splitlines(), 1):
                if "${{" in line and not line.lstrip().startswith("#"):
                    self.assertRegex(line, r"^\s*(?!description:|run:)[A-Za-z_][\w-]*:\s*\$\{\{",
                                     f"{manifest}:{number}: {line}")

    def test_a_change_to_the_required_inputs_is_made_on_purpose(self):
        """An input that comes to be required breaks every caller whose workflow does not pass it by the time its
        pin moves: a workflow started by a release runs from the file in the commit the release tags, so a release
        cut before then runs without the input however often it is run again. CHANGELOG.md lists such an input
        under Changed, saying a caller has to pass it, before REQUIRED follows. GitHub does not hold a caller to
        `required`, so this reads what a manifest promises; refusing an input left out is up to each script."""
        self.assertEqual(sorted(REQUIRED), MANIFESTS)
        for manifest in MANIFESTS:
            with self.subTest(manifest):
                self.assertEqual(required(manifest), REQUIRED[manifest])


if __name__ == "__main__":
    unittest.main()
