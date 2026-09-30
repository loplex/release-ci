"""`python3 -m unittest discover -s <directory>` on the 3.10 the actions ask for, as test.yml runs it.

The suites are written against .python-version and set themselves up with TestCase.enterContext, which arrived in
3.11. It is put back here and nothing else is: a construct newer than 3.10 in the actions' code the tests reach
still fails, and that is the failure this run is for.
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
