#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""Run unittest discovery in DIR as `python3 -m unittest discover -p
'test_*.py'` does, and fail on a skipped test as well as on a failure.

Tests that need a pinned tree or tool skip with success when it is missing, so
a job that lost one would otherwise pass. The job that runs this supplies all
of them, so any skip means its setup is broken.

  unittest-no-skips.py DIR
"""

import os
import sys
import unittest


def main(argv):
    if len(argv) != 2:
        sys.exit("usage: %s DIR" % argv[0])
    start = argv[1]
    suite = unittest.defaultTestLoader.discover(start, pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)

    for test, reason in result.skipped:
        print("SKIPPED %s: %s" % (test.id(), reason), file=sys.stderr)
    line = "%s: %d tests run, %d skipped" % (start, result.testsRun, len(result.skipped))
    print(line)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write("- %s\n" % line)

    if result.testsRun == 0:
        print("no tests found in %s" % start, file=sys.stderr)
        return 1
    if result.skipped:
        print("%d test(s) skipped: install what they need in the job, or fix "
              "the variable that points at it" % len(result.skipped), file=sys.stderr)
        return 1
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
