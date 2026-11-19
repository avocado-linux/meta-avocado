# SPDX-License-Identifier: Apache-2.0
"""Raspberry Pi kernel modules are split and stripped despite shipping as .ko.xz.

The bcm27xx defconfigs install modules xz-compressed and OE-core only splits
and strips files named .ko, so the linux-raspberrypi bbappend unpacks them in
PKGD before the split and compresses them again after it. Runs the bbappend's
two functions under bash against a fake PKGD, and its inline python for the
debug-info fragment against a fake datastore.

Run with:
    PYTHONPATH=meta-avocado/lib python3 -m unittest discover -s meta-avocado/tests
"""

import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LINUX = ROOT / "meta-avocado-raspberrypi" / "recipes-kernel" / "linux"
BBAPPEND = LINUX / "linux-raspberrypi_%.bbappend"
# usrmerge: nonarch_base_libdir is /usr/lib.
MODULES = "usr/lib/modules/6.12.87-v8/kernel/drivers/net"


def _function(name):
    m = re.search(r"^%s\(\) \{\n(.*?)^\}" % name, BBAPPEND.read_text(), re.M | re.S)
    assert m, name
    return m.group(1)


@unittest.skipUnless(shutil.which("xz") and shutil.which("bash"), "needs xz and bash")
class ModuleSplit(unittest.TestCase):
    def setUp(self):
        self.pkgd = tempfile.mkdtemp(prefix="rpi-module-split-test-")
        self.addCleanup(shutil.rmtree, self.pkgd, ignore_errors=True)
        self.dir = Path(self.pkgd, MODULES)
        self.dir.mkdir(parents=True)
        self.module = b"\x7fELF vermagic=6.12.87-v8 " + bytes(range(256)) * 64
        Path(self.dir, "foo.ko").write_bytes(self.module)
        # As the kernel's modules_install compresses.
        subprocess.run(["xz", "--check=crc32", "--lzma2=dict=1MiB", str(self.dir / "foo.ko")],
                       check=True)
        self.installed = (self.dir / "foo.ko.xz").read_bytes()

    def run_function(self, name, switch="1"):
        # bitbake substitutes these; plain strings stand in.
        body = (_function(name)
                .replace("${PKGD}", self.pkgd)
                .replace("${nonarch_base_libdir}", "/usr/lib")
                .replace("${AVOCADO_KERNEL_DEBUGINFO}", switch))
        self.assertNotIn("${", body)
        subprocess.run(["bash", "-ec", body], check=True)

    def files(self):
        return sorted(str(p.relative_to(self.dir)) for p in self.dir.rglob("*") if p.is_file())

    def test_the_split_sees_plain_modules(self):
        self.run_function("avocado_unpack_modules")
        self.assertEqual(self.files(), ["foo.ko"])
        self.assertEqual((self.dir / "foo.ko").read_bytes(), self.module)

    def test_the_packages_get_compressed_modules_and_debug_files_stay_plain(self):
        self.run_function("avocado_unpack_modules")
        (self.dir / ".debug").mkdir()
        (self.dir / ".debug" / "foo.ko").write_bytes(b"dwarf")
        self.run_function("avocado_recompress_modules")
        self.assertEqual(self.files(), [".debug/foo.ko", "foo.ko.xz"])
        # Same bytes, so the kernel's xz options too.
        self.assertEqual((self.dir / "foo.ko.xz").read_bytes(), self.installed)

    def test_both_are_off_without_the_switch(self):
        self.run_function("avocado_unpack_modules", switch="0")
        self.assertEqual(self.files(), ["foo.ko.xz"])
        Path(self.dir, "bar.ko").write_bytes(self.module)
        self.run_function("avocado_recompress_modules", switch="0")
        self.assertEqual(self.files(), ["bar.ko", "foo.ko.xz"])

    def test_they_run_around_the_split(self):
        text = BBAPPEND.read_text()
        self.assertRegex(text, r'(?m)^PACKAGE_PREPROCESS_FUNCS \+= "avocado_unpack_modules"$')
        # Before split_kernel_module_packages, which kernel-module-split adds
        # with =+, so each module package holds the .ko.xz.
        self.assertRegex(text, r'(?m)^PACKAGESPLITFUNCS:prepend = "avocado_recompress_modules "$')


class DebugInfoFragment(unittest.TestCase):
    """The switch avocado-kernel-feed reads for linux-yocto adds the Pi's fragment."""

    def src_uri(self, switch):
        lines = re.findall(r'(?m)^SRC_URI:append = "(.*\$\{@.*)"$', BBAPPEND.read_text())
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

    def test_the_fragment_builds_full_debug_info_in_the_vmlinux(self):
        # Reduced or split DWARF would leave sources out of the compiled-source
        # list.
        cfg = (LINUX / "files" / "avocado-cve-debug.cfg").read_text().splitlines()
        self.assertIn("CONFIG_DEBUG_INFO_DWARF_TOOLCHAIN_DEFAULT=y", cfg)
        self.assertIn("# CONFIG_DEBUG_INFO_REDUCED is not set", cfg)
        self.assertIn("# CONFIG_DEBUG_INFO_SPLIT is not set", cfg)
        self.assertNotIn("CONFIG_DEBUG_INFO_NONE=y", cfg)


if __name__ == "__main__":
    unittest.main()
