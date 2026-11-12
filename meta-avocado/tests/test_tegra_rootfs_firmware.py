# SPDX-License-Identifier: Apache-2.0
"""The Tegra rootfs packagegroup ships the firmware set of the machine's SoC.

meta-tegra's `tegra-firmware` umbrella requires that set (FWDEPS: the SoC's
package plus vic, shared and xusb). Naming a subpackage instead has gone wrong
twice: tegra-firmware-tegra234 left Thor (tegra264) without GPU firmware, and
tegra-firmware-${SOC_FAMILY} alone leaves it without tegra-firmware-shared
(the NVJPG firmware), which only the tegra234 package requires.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RECIPE = ROOT / "meta-avocado-nvidia/recipes-avocado/packagegroups/packagegroup-avocado-tegra-rootfs.bb"


def firmware_rdepends(text):
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    values = re.findall(r'^RDEPENDS:\$\{PN\}\s*\+?=\s*"([^"]*)"', code, re.M)
    return [pkg for value in values for pkg in value.split() if pkg.startswith("tegra-firmware")]


class TegraRootfsFirmware(unittest.TestCase):
    def test_depends_on_the_firmware_umbrella(self):
        self.assertEqual(firmware_rdepends(RECIPE.read_text()), ["tegra-firmware"])

    def test_subpackages_are_rejected(self):
        for value in ("tegra-firmware-tegra234", "tegra-firmware-${SOC_FAMILY}"):
            self.assertNotEqual(firmware_rdepends(f'RDEPENDS:${{PN}} = "{value}"'), ["tegra-firmware"], value)


if __name__ == "__main__":
    unittest.main()
