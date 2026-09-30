#!/usr/bin/env python3
"""What every action.yml this repository tracks has to be true of, read as text.

Run with `python3 -m unittest discover -s .github` from the repository's root, with the packages in
`.github/requirements.txt` installed.
"""

import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFESTS = sorted(subprocess.run(["git", "ls-files", "-z", "--", "*/action.yml"], cwd=ROOT, check=True,
                                  capture_output=True, text=True).stdout.split("\0")[:-1])


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


if __name__ == "__main__":
    unittest.main()
