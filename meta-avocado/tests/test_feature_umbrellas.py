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

import yaml

ROOT = Path(__file__).resolve().parents[2]
FEATURE = ROOT / "kas" / "feature"
QT_GROUP = ROOT / "meta-avocado" / "recipes-avocado" / "packagegroups" / "packagegroup-avocado-feature-qt.bb"

GRAPHICS_GROUP = ROOT / "meta-avocado" / "recipes-avocado" / "packagegroups" / "packagegroup-avocado-feature-graphics.bb"

# What almost-complete.yml leaves out of complete.yml, and nothing else: the
# browsers, and the Qt stack nobody builds an image with.
SLOW = {"kas/feature/browsers.yml", "kas/feature/qt.yml"}

# The webkit stack the graphics group carries: the engine, the backend only it
# uses and the launcher only it runs.
WEBKIT = {"wpewebkit", "wpebackend-fdo", "cog"}


class _Datastore:
    """Just enough of a bitbake datastore for the group's inline python."""

    def __init__(self, **values):
        self.values = values

    def getVar(self, name):
        return self.values.get(name)


def opengl_packages(skip):
    """The graphics group's OPENGL_PACKAGES with AVOCADO_SKIP_WEB_ENGINES set to skip.

    Reads the list and every unqualified :remove the way bitbake does, with no
    machine override applied.
    """
    src = GRAPHICS_GROUP.read_text()
    listing = re.search(r'^OPENGL_PACKAGES = "(.*?)"$', src, re.M | re.S).group(1)
    packages = listing.replace("\\\n", " ").split()
    d = _Datastore(AVOCADO_SKIP_WEB_ENGINES=skip)
    for expr in re.findall(r'^OPENGL_PACKAGES:remove = "\$\{@(.*)\}"$', src, re.M):
        gone = eval(expr, {"d": d}).split()
        packages = [p for p in packages if p not in gone]
    return packages


def pins(path):
    """{repo: (commit, branch)} for every repo a kas fragment lists."""
    repos = yaml.safe_load(path.read_text()).get("repos", {})
    return {name: (repo["commit"], repo["branch"]) for name, repo in repos.items()}


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

    def test_almost_complete_leaves_the_qt_stack_out(self):
        self.assertIn("kas/feature/qt.yml", includes(FEATURE / "complete.yml"))
        self.assertNotIn("kas/feature/qt.yml", includes(FEATURE / "almost-complete.yml"))

    def test_only_almost_complete_skips_web_engines(self):
        skip = re.compile(r'^\s*AVOCADO_SKIP_WEB_ENGINES\s*=\s*"1"\s*$', re.M)
        self.assertRegex((FEATURE / "almost-complete.yml").read_text(), skip)
        self.assertNotRegex((FEATURE / "complete.yml").read_text(), skip)

    def test_web_engines_repo_pins_match_the_groups_they_came_from(self):
        """web-engines.yml copies two pins by hand; this keeps the copies honest."""
        engines = pins(FEATURE / "web-engines.yml")
        self.assertEqual(engines["meta-browser"], pins(FEATURE / "browsers.yml")["meta-browser"])
        self.assertEqual(engines["meta-qt5"], pins(FEATURE / "qt.yml")["meta-qt5"])

    def test_qt_group_keeps_qtwebengine_unless_skipped(self):
        src = QT_GROUP.read_text()
        self.assertRegex(src, r"AVOCADO_SKIP_WEB_ENGINES")
        self.assertRegex(src, r"qtwebengine")


class GraphicsGroupWebkit(unittest.TestCase):
    def test_webkit_is_in_the_graphics_group_by_default(self):
        got = opengl_packages(None)
        self.assertTrue(WEBKIT <= set(got), got)
        self.assertIn("weston", got)

    def test_skipping_web_engines_drops_the_webkit_stack_and_nothing_else(self):
        kept = set(opengl_packages(None)) - WEBKIT
        self.assertEqual(set(opengl_packages("1")), kept)

    def test_other_values_of_the_variable_keep_webkit(self):
        self.assertTrue(WEBKIT <= set(opengl_packages("0")))


if __name__ == "__main__":
    unittest.main()
