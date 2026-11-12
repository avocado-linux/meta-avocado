# SPDX-License-Identifier: Apache-2.0
"""The Tegra rootfs packagegroup ships the firmware of the machine's own SoC.

It used to name tegra-firmware-tegra234 for every Tegra machine, which left a
Thor (tegra264) rootfs without GPU and display firmware.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RECIPE = ROOT / "meta-avocado-nvidia/recipes-avocado/packagegroups/packagegroup-avocado-tegra-rootfs.bb"


class TegraRootfsFirmware(unittest.TestCase):
    def test_firmware_follows_the_soc_family(self):
        code = "\n".join(line for line in RECIPE.read_text().splitlines() if not line.lstrip().startswith("#"))
        self.assertIn("tegra-firmware-${SOC_FAMILY}", code)
        self.assertIsNone(re.search(r"tegra-firmware-tegra\d", code), "a SoC's firmware is hard-coded")


if __name__ == "__main__":
    unittest.main()
