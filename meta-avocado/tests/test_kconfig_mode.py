# SPDX-License-Identifier: Apache-2.0
"""Every linux-yocto bbappend that seeds from an in-tree defconfig sets KCONFIG_MODE.

kernel-yocto merges a staged defconfig with allnoconfig unless KCONFIG_MODE
says otherwise. In-tree defconfigs are in savedefconfig form, so every option
left at its Kconfig default comes out off: on intel-x86-64 that dropped UNIX and
systemd froze in the initrd. The kernel still builds and do_kernel_configcheck
stays quiet; only a boot shows it.

Run with:
    python3 -m unittest discover -s meta-avocado/tests
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class KconfigMode(unittest.TestCase):
    def test_defconfig_seeds_set_alldefconfig(self):
        appends = sorted(ROOT.glob("meta-avocado*/recipes-kernel/linux/*.bbappend"))
        self.assertTrue(appends)
        for path in appends:
            text = path.read_text()
            for override in re.findall(r'^KBUILD_DEFCONFIG(:[\w-]+)?\s*=', text, re.M):
                with self.subTest(f"{path.relative_to(ROOT)} KBUILD_DEFCONFIG{override}"):
                    mode = r'^KCONFIG_MODE' + re.escape(override) + r'\s*=\s*"alldefconfig"'
                    self.assertIsNotNone(
                        re.search(mode, text, re.M),
                        "a defconfig seed without KCONFIG_MODE merges over allnoconfig")


if __name__ == "__main__":
    unittest.main()
