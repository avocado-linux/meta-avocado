#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""The sbom-cve-check package runs on a target image.

The scan runs the native tool, but the target package is what a user installs.
On a target image python3-core alone lacks logging and json, which the tool
imports at startup, and its database backend runs git.

  cd meta-avocado-sbom/tests && PYTHONPATH=../lib python3 -m unittest discover -p 'test_*.py'
"""

import os
import re
import unittest

RECIPE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "recipes-devtools",
                      "sbom-cve-check", "python3-sbom-cve-check_1.4.0.bb")


class ScannerRecipeTests(unittest.TestCase):
    def setUp(self):
        with open(RECIPE) as f:
            self.text = f.read()

    def test_the_target_package_pulls_in_the_standard_library_and_git(self):
        self.assertRegex(self.text,
                         r'(?m)^RDEPENDS:\$\{PN\}:append:class-target = " python3-modules git"$')

    def test_native_and_nativesdk_are_left_alone(self):
        # Native python3 carries its whole standard library; nativesdk-python3-core
        # recommends nativesdk-python3-modules.
        self.assertNotRegex(self.text,
                            r'(?m)^RDEPENDS:\$\{PN\}(:append)? *\+?= *"[^"]*(python3-modules|\bgit\b)')


if __name__ == "__main__":
    unittest.main()
