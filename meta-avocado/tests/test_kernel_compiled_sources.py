# SPDX-License-Identifier: Apache-2.0
"""Which kernels list their compiled sources, and the L4T kernels' debug info.

kas/feature/sbom.yml turns the kernel CVE filter on per kernel recipe
(SPDX_INCLUDE_COMPILED_SOURCES:pn-<kernel>) and cve-check.yml repeats the lines
for a scan stacked without sbom.yml. Every Jetson alternate kernel is in both.
The L4T kernels build reduced debug info, so avocado-linux-noble-tegra.inc adds
avocado-cve-debug.cfg on the same switch avocado-kernel-feed.bbclass reads.

Run with:
    PYTHONPATH=meta-avocado/lib python3 -m unittest discover -s meta-avocado/tests
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FEATURE = ROOT / "kas" / "feature"
NV_LINUX = ROOT / "meta-avocado-nvidia" / "recipes-kernel" / "linux"
NOBLE_INC = NV_LINUX / "avocado-linux-noble-tegra.inc"
SETTING = re.compile(r'^\s*SPDX_INCLUDE_COMPILED_SOURCES:pn-(\S+) = "1"\s*$', re.M)


def compiled_source_kernels(name):
    return SETTING.findall((FEATURE / name).read_text())


def jetson_alternate_kernels():
    text = (FEATURE / "multi-kernel-jetson.yml").read_text()
    entries = re.findall(r'AVOCADO_MULTIKERNEL_MC_RECIPES \+= "([^"]*)"', text)
    recipes = {e.split(":", 1)[1] for line in entries for e in line.split()}
    return sorted(r for r in recipes if r.startswith("linux-"))


class CompiledSourceKernels(unittest.TestCase):
    def test_no_kernel_is_listed_twice(self):
        for name in ("sbom.yml", "cve-check.yml"):
            kernels = compiled_source_kernels(name)
            self.assertEqual(len(kernels), len(set(kernels)), name)

    def test_the_scan_lists_the_kernels_the_feed_build_lists(self):
        # A scan stacked without sbom.yml must build and filter the same kernels.
        self.assertEqual(compiled_source_kernels("cve-check.yml"),
                         compiled_source_kernels("sbom.yml"))

    def test_every_jetson_alternate_kernel_is_listed(self):
        alternates = jetson_alternate_kernels()
        # Guards the parse: a short list would pass vacuously.
        self.assertEqual(alternates, ["linux-noble-nvidia-tegra", "linux-noble-nvidia-tegra-rt",
                                      "linux-yocto-rt"])
        for name in ("sbom.yml", "cve-check.yml"):
            for kernel in alternates:
                with self.subTest(fragment=name, kernel=kernel):
                    self.assertIn(kernel, compiled_source_kernels(name))

    def test_both_fragments_turn_the_debug_info_switch_on(self):
        for name in ("sbom.yml", "cve-check.yml"):
            with self.subTest(fragment=name):
                self.assertRegex((FEATURE / name).read_text(),
                                 r'(?m)^\s*AVOCADO_KERNEL_DEBUGINFO = "1"\s*$')


class L4tDebugInfoFragment(unittest.TestCase):
    def src_uri(self, switch):
        lines = re.findall(r'(?m)^SRC_URI:append = "(.*\$\{@.*)"$', NOBLE_INC.read_text())
        self.assertEqual(len(lines), 1, "the switch-keyed SRC_URI line")
        expr = re.fullmatch(r"\s*\$\{@(.*)\}", lines[0]).group(1)
        d = type("D", (), {"getVar": staticmethod(
            lambda name: {"AVOCADO_KERNEL_DEBUGINFO": switch}.get(name))})
        return eval(expr, {"d": d})

    def test_on_with_the_switch(self):
        self.assertEqual(self.src_uri("1"), "file://avocado-cve-debug.cfg")

    def test_off_without_it(self):
        self.assertEqual(self.src_uri("0"), "")
        self.assertEqual(self.src_uri(None), "")

    def test_both_l4t_kernels_take_the_shared_inc(self):
        for bbappend in ("linux-noble-nvidia-tegra_%.bbappend",
                         "linux-noble-nvidia-tegra-rt_%.bbappend"):
            with self.subTest(bbappend=bbappend):
                self.assertRegex((NV_LINUX / bbappend).read_text(),
                                 r"(?m)^require recipes-kernel/linux/avocado-linux-noble-tegra\.inc$")

    def test_the_fragment_is_on_the_inc_search_path(self):
        text = NOBLE_INC.read_text()
        m = re.search(r'(?m)^FILESEXTRAPATHS:prepend := "\$\{THISDIR\}/([^:"]+):', text)
        self.assertIsNotNone(m)
        self.assertTrue((NV_LINUX / m.group(1) / "avocado-cve-debug.cfg").is_file())

    def test_the_fragment_turns_reduced_debug_info_off_and_nothing_else(self):
        cfg = (NV_LINUX / "linux-noble-nvidia-tegra" / "avocado-cve-debug.cfg").read_text()
        options = sorted(re.findall(r"CONFIG_(\w+)", cfg))
        self.assertEqual(options, ["DEBUG_INFO_DWARF_TOOLCHAIN_DEFAULT", "DEBUG_INFO_REDUCED",
                                   "DEBUG_INFO_SPLIT", "DEBUG_KERNEL"])
        lines = cfg.splitlines()
        self.assertIn("CONFIG_DEBUG_INFO_DWARF_TOOLCHAIN_DEFAULT=y", lines)
        self.assertIn("# CONFIG_DEBUG_INFO_REDUCED is not set", lines)
        self.assertIn("# CONFIG_DEBUG_INFO_SPLIT is not set", lines)


if __name__ == "__main__":
    unittest.main()
