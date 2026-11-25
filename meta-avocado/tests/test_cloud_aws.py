# SPDX-License-Identifier: Apache-2.0
"""The cloud-aws group ships in every feed, and Greengrass runs from /var.

complete.yml is what every target's feed builds, so cloud-aws is in it.

An Avocado root filesystem is read-only and an extension delivers only /usr,
/opt and /etc, so the Greengrass nucleus is installed under /usr and run from
/var/lib/greengrass-nucleus, which tmpfiles lays out. The tmpfiles lines are run
here against a fake root to check the loader's root and the update rules.

Run with:
    python3 -m unittest discover -s meta-avocado/tests
"""

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FEATURE = ROOT / "kas" / "feature"
GG = ROOT / "meta-avocado-distro" / "dynamic-layers" / "meta-aws" / "recipes-iot" / "aws-iot-greengrass"
BIN = GG / "greengrass-bin_%.bbappend"
LITE = GG / "greengrass-lite_%.bbappend"
NUCLEUS = "packages/artifacts-unarchived/aws.greengrass.Nucleus/{pv}/aws.greengrass.nucleus"


def _var(text, name):
    return re.search(r'^%s = "([^"]*)"$' % name, text, re.M).group(1)


def _tmpfiles(pv, fake):
    """The bbappend's tmpfiles.d lines for nucleus pv, rooted under fake."""
    text = BIN.read_text()
    lines = re.search(r"<<TMPFILES\n(.*?)^TMPFILES$", text, re.M | re.S).group(1)
    return (lines.replace("${GG_VAR_ROOT}", fake + _var(text, "GG_VAR_ROOT"))
                 .replace("/${GG_BASENAME}", fake + "/" + _var(text, "GG_BASENAME"))
                 .replace("$nucleus", NUCLEUS.format(pv=pv))
                 .replace("${PV}", pv))


def _apply(lines, fake):
    """A small systemd-tmpfiles: d, L, L+ and C, as the bbappend uses them."""
    for line in lines.splitlines():
        kind, path, *_rest, arg = line.split()
        p = Path(path)
        if kind == "d":
            p.mkdir(parents=True, exist_ok=True)
        elif kind in ("L", "L+"):
            if kind == "L+" and p.is_symlink():
                p.unlink()
            if not p.is_symlink():
                p.parent.mkdir(parents=True, exist_ok=True)
                p.symlink_to(arg)
        elif kind == "C":
            if not p.exists():
                shutil.copy(arg, p)
        else:
            raise AssertionError(kind)


class Umbrella(unittest.TestCase):
    def test_every_full_umbrella_builds_cloud_aws(self):
        for name in ("complete.yml", "almost-complete.yml", "almost-complete-no-qt.yml"):
            with self.subTest(umbrella=name):
                self.assertIn("kas/feature/cloud-aws.yml", (FEATURE / name).read_text())

    def test_the_layer_is_pinned_to_wrynose(self):
        self.assertRegex((FEATURE / "cloud-aws.yml").read_text(), r"(?m)^\s+branch: wrynose$")


class GreengrassFromVar(unittest.TestCase):
    def setUp(self):
        self.fake = tempfile.mkdtemp(prefix="gg-var-test-")
        self.addCleanup(shutil.rmtree, self.fake, ignore_errors=True)
        self.seed = Path(self.fake, _var(BIN.read_text(), "GG_BASENAME"))
        self.var = Path(self.fake + _var(BIN.read_text(), "GG_VAR_ROOT"))
        (self.seed / "config").mkdir(parents=True)
        (self.seed / "config" / "config.yaml").write_text("image default\n")

    def image(self, pv):
        bindir = self.seed / NUCLEUS.format(pv=pv) / "bin"
        bindir.mkdir(parents=True)
        # The real loader's first lines: its root is four levels above its path.
        (bindir / "loader").write_text('PWD=$(dirname "$0")\nGG_ROOT=$(cd $PWD/../../../..; pwd)\n'
                                      'echo "$GG_ROOT"\n')
        _apply(_tmpfiles(pv, self.fake), self.fake)

    def loader_root(self):
        loader = self.var / "alts" / "current" / "distro" / "bin" / "loader"
        return subprocess.run(["sh", str(loader)], capture_output=True, text=True,
                              check=True).stdout.strip()

    def test_the_loader_runs_from_var(self):
        self.image("2.16.0")
        self.assertEqual(self.loader_root(), str(self.var))

    def test_an_os_update_runs_the_new_nucleus(self):
        self.image("2.16.0")
        self.image("2.17.0")
        self.assertIn("2.17.0", os.path.realpath(self.var / "alts" / "init" / "distro"))

    def test_a_provisioned_config_and_a_deployed_nucleus_stay(self):
        self.image("2.16.0")
        (self.var / "config" / "config.yaml").write_text("provisioned\n")
        (self.var / "alts" / "current").unlink()
        (self.var / "alts" / "current").symlink_to(self.var / "alts" / "old")
        self.image("2.17.0")
        self.assertEqual((self.var / "config" / "config.yaml").read_text(), "provisioned\n")
        self.assertEqual(os.readlink(self.var / "alts" / "current"), str(self.var / "alts" / "old"))

    def test_the_service_starts_the_loader_through_var_and_is_not_enabled(self):
        text = BIN.read_text()
        self.assertIn('s,/${GG_BASENAME}/alts/current,${GG_VAR_ROOT}/alts/current,g', text)
        self.assertIn("ExecStartPre=systemd-tmpfiles --create greengrass-bin.conf", text)
        self.assertRegex(text, r'(?m)^SYSTEMD_AUTO_ENABLE = "disable"$')
        self.assertNotRegex(_var(text, "GG_BASENAME"), r"^(var|greengrass)")

    def test_the_root_is_not_inside_greengrass_lites(self):
        # Greengrass Lite's working dir, owned by its own user.
        self.assertFalse((_var(BIN.read_text(), "GG_VAR_ROOT") + "/").startswith("/var/lib/greengrass/"))

    def test_no_plugin_lands_outside_usr(self):
        self.assertRegex(BIN.read_text(), r'(?m)^PACKAGECONFIG:remove = "fleetprovisioning"$')


class OneAwsCRuntime(unittest.TestCase):
    """Only one package in a feed ships libaws-crt-cpp.so."""

    def test_neither_recipe_bundles_its_own(self):
        sdk = ROOT / "meta-avocado-distro" / "dynamic-layers" / "meta-aws" / "recipes-sdk"
        for recipe in ("aws-crt-cpp", "aws-iot-device-sdk-cpp-v2"):
            with self.subTest(recipe=recipe):
                text = (sdk / recipe / f"{recipe}_%.bbappend").read_text()
                self.assertRegex(text, r'(?m)^PACKAGECONFIG:remove = "build-deps"$')


class GreengrassLite(unittest.TestCase):
    def test_its_working_dir_is_made_at_boot(self):
        text = LITE.read_text()
        self.assertIn('echo "d ${gg_workingdir} 0755 ${gg_user} ${gg_group} -"', text)
        self.assertIn("tmpfiles.d/greengrass-lite.conf", text)


if __name__ == "__main__":
    unittest.main()
