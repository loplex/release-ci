"""A repository built for the tests that ask git about tags and branches.

Not a test file itself: unittest discovers only `test*.py`.
"""

import subprocess
import tempfile
import unittest
from pathlib import Path

from rules import repository


class TwoReleasesOneOffMain(unittest.TestCase):
    """`v0.1.0` on main, and `v0.2.0` on `release/0.2.0` and `aside`, which main has not taken in.
    The checked repository points here for the length of each test."""

    def setUp(self):
        self.here = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        original = repository.REPO
        repository.REPO = self.here
        self.addCleanup(setattr, repository, "REPO", original)
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
