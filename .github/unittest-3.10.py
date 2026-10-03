"""`python3 -m unittest discover -s <directory>` on Python 3.10, the version the actions ask for, as test.yml runs it.

The suites are written against .python-version and use TestCase.enterContext, which arrived in 3.11.
This file adds that one method and nothing else.
Anything else newer than 3.10 in the actions' code that the tests reach still fails,
and catching that is what this run is for.
"""

import sys
import unittest

if not hasattr(unittest.TestCase, "enterContext"):
    def enter_context(self, manager):
        # What 3.11 does: enter now, and exit among the test's cleanups.
        entered = type(manager).__enter__(manager)
        self.addCleanup(type(manager).__exit__, manager, None, None, None)
        return entered

    unittest.TestCase.enterContext = enter_context

unittest.main(module=None, argv=["python3 -m unittest", "discover", "-s", *sys.argv[1:]])
