# SPDX-License-Identifier: Apache-2.0
"""Every kernel in a multi-kernel feed ships its own kernel-devsrc.

Out-of-tree modules compile against kernel-devsrc. avocado-cli picks the
selected kernel's copy by excluding every other kernel's `kernel-*<kver>`
packages, which only works when the package NAME carries the full
KERNEL_VERSION, and only finds a copy when the alt kernel's multiconfig
builds one.

Run with:
    PYTHONPATH=meta-avocado/lib python3 -m unittest discover -s meta-avocado/tests
"""

import re
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BBAPPEND = ROOT / "meta-avocado-distro" / "recipes-kernel" / "linux" / "kernel-devsrc.bbappend"
MC_RECIPES = re.compile(r'AVOCADO_MULTIKERNEL_MC_RECIPES\s*\+=\s*"([^"]*)"')


def _mc_recipes():
    """{mc: {recipe, ...}} across every kas file."""
    found = {}
    for path in sorted((ROOT / "kas").rglob("*.yml")):
        for value in MC_RECIPES.findall(path.read_text()):
            for entry in value.split():
                mc, _, recipe = entry.partition(":")
                found.setdefault(mc, set()).add(recipe)
    return found


def _kernel_mcs():
    return {mc: r for mc, r in _mc_recipes().items() if any(x.startswith("linux-") for x in r)}


def _assignments():
    return dict(re.findall(r'^(\S+)\s*\+?=\s*"([^"]*)"', BBAPPEND.read_text(), re.M))


class KernelDevsrc(unittest.TestCase):
    def test_alt_kernel_mcs_are_found(self):
        # Guards the discovery below: an empty set would pass vacuously.
        self.assertGreaterEqual(len(_kernel_mcs()), 2)

    def test_every_alt_kernel_mc_builds_its_devsrc(self):
        for mc, recipes in _kernel_mcs().items():
            with self.subTest(mc=mc):
                self.assertIn("kernel-devsrc", recipes)

    def test_package_names_carry_the_kernel_version(self):
        a = _assignments()
        self.assertIn("KERNEL_VERSION", a["KERNEL_DEVSRC_KVER"])
        for pkg in ("${PN}", "${PN}-dev", "${PN}-dbg"):
            with self.subTest(pkg=pkg):
                # Ends in the version, so avocado-cli's end-anchored
                # `kernel-*<kver>` exclude matches it.
                self.assertTrue(a[f"PKG:{pkg}"].endswith("-${KERNEL_DEVSRC_KVER}"))
                # The bare name stays resolvable: without RPROVIDES, BitBake
                # rewrites a bare RDEPENDS to the default kernel's package.
                self.assertEqual(a[f"RPROVIDES:{pkg}"], pkg)
                # The old unversioned package is obsoleted on upgrade.
                self.assertEqual(a[f"RREPLACES:{pkg}"], pkg)

    def test_unknown_kernel_version_is_fatal(self):
        # module-base.bbclass reads KERNEL_VERSION with oe.utils.read_file,
        # which returns "" when kernel-abiversion is missing. Run the guard
        # itself: it must stop the build on "" and let a real version through.
        body = re.search(r"^python do_package:prepend\(\) \{\n(.*?)^\}", BBAPPEND.read_text(), re.M | re.S)
        self.assertIsNotNone(body, "the do_package:prepend guard is gone")
        code = textwrap.dedent(body.group(1))

        class Fatal(Exception):
            pass

        class Bb:
            @staticmethod
            def fatal(msg):
                raise Fatal(msg)

            note = warn = staticmethod(lambda msg: None)

        def run(kver):
            d = type("D", (), {"getVar": staticmethod(lambda name: {"KERNEL_DEVSRC_KVER": kver}.get(name))})
            exec(code, {"d": d, "bb": Bb})

        with self.assertRaises(Fatal):
            run("")
        run("6.18.52-yocto-standard")


if __name__ == "__main__":
    unittest.main()
