# SPDX-License-Identifier: Apache-2.0
"""Serial-console-only boards pull systemd-serial-console-preset into the rootfs.

Without it OE-core's getty@.service preset gives getty@getty.service, which
fails on every boot and leaves systemd `degraded`. The preset has to come from
the rootfs packagegroup: packagegroup-avocado-rootfs.bb does not expand
MACHINE_ESSENTIAL_EXTRA_RDEPENDS, and a feed-only packagegroup never reaches a
runtime that does not install it.

Run with:
    python3 -m unittest discover -s meta-avocado/tests
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# bbappend or packagegroup -> the override its RDEPENDS append must carry.
WIRING = {
    "meta-avocado-raspberrypi/recipes-avocado/packagegroups/packagegroup-avocado-rootfs.bbappend": "rpi",
    "meta-avocado-qcom/recipes-avocado/packagegroups/packagegroup-avocado-rootfs.bbappend": "rubikpi3",
}


class SerialConsolePreset(unittest.TestCase):
    def test_rootfs_groups_pull_the_preset(self):
        for rel, override in WIRING.items():
            with self.subTest(rel):
                text = (ROOT / rel).read_text()
                line = re.search(
                    r'^RDEPENDS:\$\{PN\}:append:' + re.escape(override) + r'\s*=\s*"([^"]*)"',
                    text, re.M)
                self.assertIsNotNone(line, f"no RDEPENDS:${{PN}}:append:{override} in {rel}")
                self.assertIn("systemd-serial-console-preset", line.group(1).split())


if __name__ == "__main__":
    unittest.main()
