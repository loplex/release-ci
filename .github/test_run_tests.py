#!/usr/bin/env python3
"""What run-tests.sh reports: a green suite, a red one, and a suite whose tests did not all run.

It runs over a checkout made for the purpose, with five suites of a few tests each, not over this repository:
here it would run this test again.

Run with `python3 -m unittest discover -s .github` from the repository's root.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RUN_TESTS = Path(__file__).resolve().parent / "run-tests.sh"

PASSING = ("import unittest\n\n\nclass T(unittest.TestCase):\n    def test_a(self):\n        pass\n\n"
           "    def test_b(self):\n        pass\n")


class RunTests(unittest.TestCase):
    def setUp(self):
        self.tree = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        subprocess.run(["git", "init", "-q"], cwd=self.tree, check=True)
        for suite in ("lib", "check-release", "release-flow", "intellij"):
            (self.tree / suite / "tests").mkdir(parents=True)
            (self.tree / suite / "tests" / "__init__.py").write_text("", encoding="utf-8")
            (self.tree / suite / "tests" / "test_one.py").write_text(PASSING, encoding="utf-8")
        (self.tree / ".github").mkdir()
        (self.tree / ".github" / "test_one.py").write_text(PASSING, encoding="utf-8")

    def run_tests(self, python=sys.executable):
        # Run from a directory below the root: the checkout is found from wherever the script is run in it.
        return subprocess.run(["bash", str(RUN_TESTS)], cwd=self.tree / "lib", capture_output=True, text=True,
                              env={**os.environ, "PYTHON": str(python)})

    def test_green_suites_each_say_how_many_tests_ran(self):
        done = self.run_tests()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(done.stdout, "lib: OK, 2 tests\ncheck-release: OK, 2 tests\nrelease-flow: OK, 2 tests\n"
                                      "intellij: OK, 2 tests\n.github: OK, 2 tests\n")

    def test_a_failing_test_makes_its_suite_red_and_shows_its_output(self):
        module = self.tree / "release-flow" / "tests" / "test_one.py"
        module.write_text(PASSING.replace("pass\n\n    def test_b", "self.fail('no')\n\n    def test_b"),
                          encoding="utf-8")
        done = self.run_tests()
        self.assertEqual(done.returncode, 1)
        self.assertIn("release-flow: FAILED, 2 of 2 tests ran\n", done.stdout)
        self.assertIn("lib: OK, 2 tests\n", done.stdout)
        self.assertIn("===== release-flow\n", done.stdout)
        self.assertIn("AssertionError: no", done.stdout)
        self.assertNotIn("===== lib\n", done.stdout)

    def test_a_module_that_does_not_import_makes_its_suite_red(self):
        (self.tree / "intellij" / "tests" / "test_two.py").write_text("import nowhere_to_be_found\n", encoding="utf-8")
        done = self.run_tests()
        self.assertEqual(done.returncode, 1)
        self.assertIn("intellij: FAILED, 2 of 2 tests ran\n", done.stdout)
        self.assertIn("ModuleNotFoundError: No module named 'nowhere_to_be_found'", done.stdout)

    def test_tests_that_did_not_run_make_their_suite_red(self):
        """A Python that answers for the tests of check-release without running them: green, and none ran."""
        python = self.tree / "python-stub"
        python.write_text("#!/usr/bin/env bash\n"
                          'for argument; do [[ $argument == tests.test_one.* ]] && [[ $PWD == */check-release ]] '
                          "&& exit 0; done\n"
                          f'exec "{sys.executable}" "$@"\n', encoding="utf-8")
        python.chmod(0o755)
        done = self.run_tests(python)
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("check-release: FAILED, 0 of 2 tests ran\n", done.stdout)
        self.assertIn("lib: OK, 2 tests\n", done.stdout)

    def test_a_suite_the_checkout_does_not_have_is_no_failure(self):
        """An older commit may come before a suite."""
        shutil.rmtree(self.tree / "intellij")
        done = self.run_tests()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("intellij: absent\n", done.stdout)


if __name__ == "__main__":
    unittest.main()
