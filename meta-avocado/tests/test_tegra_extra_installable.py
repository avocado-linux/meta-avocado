# SPDX-License-Identifier: Apache-2.0
"""packagegroup-avocado-tegra-extra only requires packages a feed can carry.

The group's RPM lands in every Jetson feed, so each name it RDEPENDS on must
be a real package there, or `avocado install` fails with "nothing provides".
Two names never were:

- tegra-binaries unpacks the L4T BSP for other recipes and has PACKAGES = "".
- kernel-module-r8168 is an NVIDIA OOT module built only for the 5.15 L4T
  kernel, so linux-yocto feeds have no provider. Kernel modules are per kernel
  and belong in that kernel's module groups (see test_tegra_oot_per_kernel).

Run with:
    PYTHONPATH=meta-avocado/lib python3 -m unittest discover -s meta-avocado/tests
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GROUP = (
    ROOT / "meta-avocado-nvidia" / "recipes-avocado" / "packagegroups"
    / "packagegroup-avocado-tegra-extra.bb"
)

# Recipes that ship no package, so a runtime dependency on them never resolves.
NO_PACKAGE_RECIPES = {"tegra-binaries"}


def _rdepends():
    text = GROUP.read_text()
    body = re.search(r'^RDEPENDS:\$\{PN\} = "(.*?)"', text, re.M | re.S).group(1)
    return body.replace("\\", " ").split()


class TegraExtraInstallable(unittest.TestCase):
    def test_no_recipe_without_packages(self):
        self.assertEqual(sorted(NO_PACKAGE_RECIPES & set(_rdepends())), [])

    def test_no_kernel_modules(self):
        modules = [d for d in _rdepends() if re.match(r"(nv-)?kernel-module-", d)]
        self.assertEqual(modules, [])


if __name__ == "__main__":
    unittest.main()
