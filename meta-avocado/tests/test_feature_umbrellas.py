# SPDX-License-Identifier: Apache-2.0
"""kas/feature/complete.yml and almost-complete.yml: how the two umbrellas relate.

complete.yml is what CI and the build cluster build, so its meaning must not
move. almost-complete.yml is the same set without the two whole-browser
compiles (chromium and qtwebengine); this checks that the two lists cannot
drift apart and that only the almost-complete umbrella turns qtwebengine off.

Run with:
    python3 -m unittest discover -s meta-avocado/tests
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FEATURE = ROOT / "kas" / "feature"
QT_GROUP = ROOT / "meta-avocado" / "recipes-avocado" / "packagegroups" / "packagegroup-avocado-feature-qt.bb"

# What almost-complete.yml leaves out of complete.yml, and nothing else.
SLOW = {"kas/feature/browsers.yml"}


def includes(path):
    """The kas/feature/*.yml fragments an umbrella lists, in order."""
    return re.findall(r"^\s*file:\s*(kas/feature/\S+\.yml)\s*$", path.read_text(), re.M)


class Umbrellas(unittest.TestCase):
    def test_complete_still_includes_browsers(self):
        self.assertIn("kas/feature/browsers.yml", includes(FEATURE / "complete.yml"))

    def test_almost_complete_is_complete_minus_the_slow_fragments(self):
        complete = includes(FEATURE / "complete.yml")
        almost = includes(FEATURE / "almost-complete.yml")
        self.assertEqual(almost, [f for f in complete if f not in SLOW])

    def test_only_almost_complete_skips_web_engines(self):
        skip = re.compile(r'^\s*AVOCADO_SKIP_WEB_ENGINES\s*=\s*"1"\s*$', re.M)
        self.assertRegex((FEATURE / "almost-complete.yml").read_text(), skip)
        self.assertNotRegex((FEATURE / "complete.yml").read_text(), skip)

    def test_qt_group_keeps_qtwebengine_unless_skipped(self):
        src = QT_GROUP.read_text()
        self.assertRegex(src, r"AVOCADO_SKIP_WEB_ENGINES")
        self.assertRegex(src, r"qtwebengine")


if __name__ == "__main__":
    unittest.main()
