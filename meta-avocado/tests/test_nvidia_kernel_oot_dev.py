# SPDX-License-Identifier: Apache-2.0
"""Every kernel in a multi-kernel Tegra feed ships its own nvidia-oot -dev.

Out-of-tree modules built against nvidia-oot (an SDK compile) need the
Module.symvers, headers and generated conftest headers of the nvidia-oot build
for the kernel they target: the L4T kernel's CONFIG_MODVERSIONS refuses CRCs
from another kernel's build. avocado-cli keeps only the selected kernel's
copy by excluding every other kernel's `kernel-*<kver>` packages, so the -dev
package NAME must start with `kernel-` and end in the full KERNEL_VERSION.

Run with:
    PYTHONPATH=meta-avocado/lib python3 -m unittest discover -s meta-avocado/tests
"""

import fnmatch
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BBAPPEND = ROOT / "meta-avocado-nvidia" / "recipes-kernel" / "nvidia-kernel-oot" / "nvidia-kernel-oot_%.bbappend"


def _value(var):
    m = re.search(r"^" + re.escape(var) + r'\s*\+?=\s*"([^"]*)"', BBAPPEND.read_text(), re.M)
    return m.group(1) if m else None


class NvidiaKernelOotDev(unittest.TestCase):
    def test_dev_package_is_named_per_kernel(self):
        pkg = _value("PKG:${PN}-dev")
        self.assertIsNotNone(pkg, "nvidia-kernel-oot -dev is not renamed per kernel")
        self.assertTrue(pkg.endswith("-${KERNEL_VERSION}"), pkg)
        # avocado-cli's off-kernel exclude must hide the other kernels' copies.
        l4t = pkg.replace("${KERNEL_VERSION}", "6.8.12-l4t-r39.2.1-1021.21")
        self.assertTrue(fnmatch.fnmatch(l4t, "kernel-*6.8.12-l4t-r39.2.1-1021.21"), l4t)
        self.assertFalse(fnmatch.fnmatch(l4t, "kernel-*6.18.52-yocto-standard"), l4t)

    def test_bare_name_stays_resolvable(self):
        self.assertIn("${PN}-dev", _value("RPROVIDES:${PN}-dev").split())

    def test_conftest_headers_are_staged(self):
        text = BBAPPEND.read_text()
        # conftest.h includes the per-category headers beside it: both the
        # top-level header and the directory must be installed, not just made.
        self.assertIn("install -d ${D}${includedir}/${BPN}/nvidia/conftest\n", text)
        self.assertIn(
            "${S}/out/nvidia-conftest/nvidia/conftest.h ${D}${includedir}/${BPN}/nvidia/conftest.h\n", text
        )
        self.assertIn(
            "${S}/out/nvidia-conftest/nvidia/conftest/*.h ${D}${includedir}/${BPN}/nvidia/conftest/\n", text
        )


if __name__ == "__main__":
    unittest.main()
