# SPDX-License-Identifier: Apache-2.0
"""Each Jetson kernel installs its own NVIDIA out-of-tree modules.

nvidia-kernel-oot is built once per kernel, and its unversioned packages
(nvidia-kernel-oot-base and the rest) share one name across kernels, while
the module names they require are provided by every kernel's build. dnf picks
the newest NVR, so a 5.15 rootfs could install the 6.6 modules. The per-kernel
OOT group therefore names this kernel's module packages, and each kernel's
module group links to its own OOT group by the versioned name.

Run with:
    PYTHONPATH=meta-avocado/lib python3 -m unittest discover -s meta-avocado/tests
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RECIPES = ROOT / "meta-avocado-nvidia" / "recipes-kernel"
OOT = RECIPES / "nvidia-kernel-oot" / "nvidia-kernel-oot_%.bbappend"
KERNELS = [
    RECIPES / "linux" / "linux-yocto_%.bbappend",
    RECIPES / "linux" / "linux-jammy-nvidia-tegra_%.bbappend",
]
GROUP = "packagegroup-avocado-rootfs-modules-oot"


class FakeData:
    def __init__(self, values):
        self.values = dict(values)

    def getVar(self, name):
        return self.values.get(name)

    def setVar(self, name, value):
        self.values[name] = value


def _run_group_func(values):
    body = re.search(
        r"^python avocado_oot_group_this_kernel\(\) \{\n(.*?)^\}", OOT.read_text(), re.M | re.S
    ).group(1)
    d = FakeData(values)
    exec("def f(d):\n" + body, globals())
    f(d)  # noqa: F821 - defined by the exec above
    return d.getVar("RDEPENDS:" + GROUP).split()


class TegraOotPerKernel(unittest.TestCase):
    def test_the_group_names_this_kernels_modules(self):
        kv = "5.15.199-l4t-r36.5-1050.50"
        deps = _run_group_func({
            "KERNEL_MODULE_PACKAGE_PREFIX": "nv-",
            "KERNEL_VERSION": kv,
            "TEGRA_OOT_BASE_DRIVERS": "nv-kernel-module-nvgpu nv-kernel-module-host1x",
            # host1x is built in tree by this kernel, so there is no OOT package.
            "PACKAGES": f"nvidia-kernel-oot nv-kernel-module-nvgpu-{kv}",
        })
        self.assertEqual(deps, [f"nv-kernel-module-nvgpu-{kv}", f"kernel-module-host1x-{kv}"])

    def test_it_runs_at_packaging_time(self):
        self.assertRegex(OOT.read_text(), r'PACKAGESPLITFUNCS \+= "avocado_oot_group_this_kernel"')

    def test_the_versioned_group_resolves_at_parse_time(self):
        dynamic = re.findall(r'^PACKAGES_DYNAMIC \+= "([^"]*)"', OOT.read_text(), re.M)
        self.assertTrue(any(re.match(p, f"{GROUP}-6.6.151-yocto-standard") for p in dynamic))

    def test_each_kernel_links_its_own_oot_group(self):
        for path in KERNELS:
            with self.subTest(kernel=path.name):
                text = path.read_text()
                self.assertIn(f"{GROUP}-${{KERNEL_VERSION}}", text)
                self.assertNotRegex(text, rf"{GROUP}[ \"]")


if __name__ == "__main__":
    unittest.main()
