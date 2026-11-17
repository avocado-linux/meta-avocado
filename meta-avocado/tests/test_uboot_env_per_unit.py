# SPDX-License-Identifier: Apache-2.0
"""No U-Boot env file bakes in a value U-Boot should read from the board.

U-Boot sets serial# and the MAC variables from the hardware only when they
are unset, and then writes them into the device tree. Every Raspberry Pi env
file once carried serial#=1000000088c98f3b, a printenv dump from one board,
so every Avocado Pi reported the same serial in /proc/cpuinfo and the device
tree, and anything keyed on it merged distinct boards into one.

Run with:
    python3 -m unittest discover -s meta-avocado/tests
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

PER_UNIT = re.compile(r"^\s*(serial#|ethaddr|eth\d+addr|usbethaddr)\s*=")


class UbootEnvPerUnit(unittest.TestCase):
    def test_env_files_leave_per_unit_values_unset(self):
        envs = sorted(ROOT.glob("meta-avocado*/**/recipes-bsp/u-boot/*/env/*.txt"))
        self.assertTrue(any("raspberrypi" in str(p) for p in envs))
        for path in envs:
            for n, line in enumerate(path.read_text().splitlines(), 1):
                with self.subTest(f"{path.relative_to(ROOT)}:{n}"):
                    self.assertIsNone(
                        PER_UNIT.match(line),
                        "per-unit value baked into the env; U-Boot reads it from the board when unset")


if __name__ == "__main__":
    unittest.main()
