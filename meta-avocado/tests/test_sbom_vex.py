# SPDX-License-Identifier: Apache-2.0
"""kas/feature/sbom.yml and cve-check.yml: SPDX_INCLUDE_VEX in a feed build and a CVE scan.

The CVE scan rebuilds the feed and should take the SPDX tasks from the feed
build's sstate, which only works if both resolve SPDX_INCLUDE_VEX to the same
value. create-spdx-3.0 assigns it with ??= and is inherited after local.conf
is parsed; of two ??= the last one parsed wins, so a ??= in local.conf never
takes effect.

Run with:
    python3 -m unittest discover -s meta-avocado/tests
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FEATURE = ROOT / "kas" / "feature"


def mentions(name):
    """Every non-comment line naming the variable: overrides, export and unset included."""
    lines = (FEATURE / name).read_text().splitlines()
    return [l.strip() for l in lines if "SPDX_INCLUDE_VEX" in l and not l.lstrip().startswith("#")]


class SpdxIncludeVex(unittest.TestCase):
    def test_sbom_sets_it_with_a_default_the_class_cannot_override(self):
        self.assertEqual(mentions("sbom.yml"), ['SPDX_INCLUDE_VEX ?= "all"'])

    def test_scan_sets_the_same_value(self):
        self.assertEqual(mentions("cve-check.yml"), ['SPDX_INCLUDE_VEX = "all"'])


def inherits(name):
    lines = (FEATURE / name).read_text().splitlines()
    return [l.strip() for l in lines
            if l.strip().startswith("INHERIT") and "create-spdx" in l]


class Spdx30(unittest.TestCase):
    """scarthgap's create-spdx is 2.2, and sbom-cve-check reads 3.0 and fails
    the scan without create-spdx-3.0, so a scan stacked without sbom.yml has to
    switch the class itself."""

    SWITCH = ['INHERIT:remove = "create-spdx"', 'INHERIT += "create-spdx-3.0"']

    def test_sbom_switches_to_3_0(self):
        self.assertEqual(inherits("sbom.yml"), self.SWITCH)

    def test_scan_switches_to_3_0(self):
        self.assertEqual(inherits("cve-check.yml"), self.SWITCH)


if __name__ == "__main__":
    unittest.main()
