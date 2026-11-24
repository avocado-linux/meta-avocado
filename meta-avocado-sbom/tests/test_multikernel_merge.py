#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""The RPM manifest lists exactly the alternate-kernel RPMs the merge published.

Runs avocado-multikernel.bbclass's do_multikernel_merge under bash, against a
fake pair of deploy trees and the alternate tree's sstate manifests, then
builds the manifest from the list it wrote with avocado-cve-report's own
do_rpm_manifest at feed scope.

  python3 -m unittest discover -s meta-avocado-sbom/tests -p 'test_*.py'
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
sys.path.insert(0, HERE)

from avocado_sbom import rpms  # noqa: E402
from test_rpms import rpm_bytes  # noqa: E402

BBCLASS = os.path.join(HERE, "..", "..", "meta-avocado-distro", "classes",
                       "avocado-multikernel.bbclass")
REPORT_BB = os.path.join(HERE, "..", "recipes-avocado", "avocado-cve-report",
                         "avocado-cve-report.bb")
MC = "jetson-l4t"
ARCH = "armv8a"
L4T = "5.15.199-l4t-r36.5"
MACHINE = "avocado-jetson-orin-nx"
KERNEL = "linux-noble-nvidia-tegra"
OOT = "nvidia-kernel-oot"
MC_RECIPES = "%s:%s %s:%s" % (MC, KERNEL, MC, OOT)

class Fatal(Exception):
    pass

def report_rpm_manifest(values):
    """Run avocado-cve-report's do_rpm_manifest, with the recipe's own helper
    functions, against a datastore holding values."""
    with open(REPORT_BB) as f:
        text = f.read()
    m = re.search(r"^python do_rpm_manifest\(\) \{\n(.*?)^\}\n", text, re.M | re.S)
    assert m, "do_rpm_manifest not found in %s" % REPORT_BB

    def fatal(msg):
        raise Fatal(msg)

    def remove(path):
        if os.path.lexists(path):
            os.remove(path)
    bb = types.SimpleNamespace(fatal=fatal, warn=lambda *a: None, note=lambda *a: None,
                               plain=lambda *a: None, utils=types.SimpleNamespace(remove=remove))
    d = types.SimpleNamespace(getVar=lambda name: values.get(name))
    ns = {"bb": bb, "os": os}
    for block in re.findall(r"^(def \w+\(.*?)(?=^\S)", text + "\n#", re.M | re.S):
        exec(block, ns)
    exec("def task(d):\n" + textwrap.indent(textwrap.dedent(m.group(1)), "    "), ns)
    ns["task"](d)

def merge_body():
    with open(BBCLASS) as f:
        text = f.read()
    m = re.search(r"^do_multikernel_merge\(\) \{\n(.*?)^\}\naddtask multikernel_merge",
                  text, re.S | re.M)
    assert m, "do_multikernel_merge not found in %s" % BBCLASS
    return m.group(1)

@unittest.skipUnless(shutil.which("bash"), "bash not installed")
class MergeListTests(unittest.TestCase):
    def setUp(self):
        self.top = tempfile.mkdtemp(prefix="avocado-multikernel-test-")
        self.addCleanup(shutil.rmtree, self.top, ignore_errors=True)
        self.deploy = os.path.join(self.top, "tmp", "deploy")
        self.alt_base = os.path.join(self.top, "tmp-%s" % MC)
        self.alt_rpm = os.path.join(self.alt_base, "deploy", "rpm")
        self.feed = os.path.join(self.deploy, "rpm")
        os.makedirs(self.feed)
        self.owned = {}

    def rpm(self, rpm_dir, name, version, release="r0.1", epoch=None, recipe=None):
        rel = "%s/%s-%s-%s.%s.rpm" % (ARCH, name, version, release, ARCH)
        path = os.path.join(rpm_dir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(rpm_bytes(name, version, release, ARCH, epoch=epoch))
        if recipe:
            self.owned.setdefault(recipe, []).append(path)
        return rel

    def write_sstate_manifests(self):
        # What do_package_write_rpm's sstate manifest lists: the directory it
        # created and every file it installed into DEPLOY_DIR_RPM.
        control = os.path.join(self.alt_base, "sstate-control")
        os.makedirs(control, exist_ok=True)
        for recipe, paths in self.owned.items():
            name = "manifest-%s-%s.package_write_rpm" % (ARCH, recipe)
            with open(os.path.join(control, name), "w") as f:
                f.write("%s/%s/\n" % (self.alt_rpm, ARCH))
                for path in paths:
                    f.write(path + "\n")

    def merge(self, check=True):
        # bitbake substitutes these datastore variables; plain shell variables
        # of the same names stand in for them.
        script = "\n".join([
            "set -e",
            "bbnote() { :; }",
            "bbwarn() { echo \"WARNING: $*\" >&2; }",
            "bbfatal() { echo \"ERROR: $*\" >&2; exit 1; }",
            'AVOCADO_MULTIKERNEL_MC_RECIPES="%s"' % MC_RECIPES,
            'TOPDIR="%s"' % self.top,
            'DEPLOY_DIR="%s"' % self.deploy,
            "do_multikernel_merge() {",
            merge_body(),
            "}",
            "do_multikernel_merge",
        ])
        return subprocess.run(["bash", "-c", script], capture_output=True,
                              text=True, check=check)

    def listed(self):
        return rpms.read_merged_rpms(rpms.merged_rpms_path(self.deploy, MC))

    def pkgdata(self, tmp, recipe, packages):
        reverse = os.path.join(self.top, tmp, "pkgdata", "jetson", "runtime-reverse")
        os.makedirs(reverse, exist_ok=True)
        for name, (pkgv, pkgr) in packages.items():
            with open(os.path.join(reverse, name), "w") as f:
                f.write("PN: %s\nPV: %s\nPKGV: %s\nPKGR: %s\nPKGSIZE:%s: 10\n"
                        % (recipe, pkgv, pkgv, pkgr, name))

    def build_trees(self):
        # The default multiconfig's feed already holds nvidia-kernel-oot's own
        # package, built against its own kernel; the alternate tree built the
        # same NEVRA into a different file.
        self.rpm(self.feed, OOT, "36.5.2", "r0.3")
        self.rpm(self.feed, "base-files", "3.0.14")
        self.rpm(self.alt_rpm, "kernel-%s" % L4T, "5.15.199+git0+abc", recipe=KERNEL)
        self.rpm(self.alt_rpm, "nv-kernel-module-nvidia-%s" % L4T, "36.5.2", "r0.3",
                 recipe=OOT)
        self.rpm(self.alt_rpm, OOT, "36.5.2", "r0.3", epoch=1, recipe=OOT)
        # Built in the alternate tree, not by a recipe it names.
        self.rpm(self.alt_rpm, "base-files", "3.0.14", epoch=1)
        self.write_sstate_manifests()

    def feed_trees(self):
        self.build_trees()
        self.pkgdata("tmp", "base-files", {"base-files": ("3.0.14", "r0.1")})
        self.pkgdata("tmp", OOT, {OOT: ("36.5.2", "r0.3")})
        alt = "tmp-%s" % MC
        self.pkgdata(alt, KERNEL, {"kernel-%s" % L4T: ("5.15.199+git0+abc", "r0.1")})
        self.pkgdata(alt, OOT, {"nv-kernel-module-nvidia-%s" % L4T: ("36.5.2", "r0.3"),
                                OOT: ("36.5.2", "r0.3")})
        self.pkgdata(alt, "base-files", {"base-files": ("3.0.14", "r0.1")})

    def feed_rpm_manifest(self):
        out = os.path.join(self.deploy, "avocado-cve", "avocado-rpm-manifest.json")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        tmp = os.path.join(self.top, "tmp")
        report_rpm_manifest({
            "AVOCADO_CVE_SCOPE": "feed", "MACHINE": MACHINE, "DISTRO_VERSION": "2026.1",
            "TOPDIR": self.top, "TMPDIR": tmp, "DEPLOY_DIR": self.deploy,
            "DEPLOY_DIR_RPM": self.feed,
            "PKGDATA_DIR": os.path.join(tmp, "pkgdata", "jetson"),
            "AVOCADO_RPM_MANIFEST_FILE": out,
            "AVOCADO_MULTIKERNEL_MC_RECIPES": MC_RECIPES,
        })
        with open(out) as f:
            return json.load(f)

    def test_the_list_is_what_the_feed_serves_from_the_merge(self):
        self.build_trees()
        self.merge()
        self.assertEqual(self.listed(), {
            "%s/kernel-%s-5.15.199+git0+abc-r0.1.%s.rpm" % (ARCH, L4T, ARCH),
            "%s/nv-kernel-module-nvidia-%s-36.5.2-r0.3.%s.rpm" % (ARCH, L4T, ARCH),
            # Already in the feed, the default's copy: still served.
            "%s/%s-36.5.2-r0.3.%s.rpm" % (ARCH, OOT, ARCH),
        })
        on_disk = {os.path.relpath(os.path.join(root, f), self.feed)
                   for root, _dirs, files in os.walk(self.feed) for f in files}
        self.assertLessEqual(self.listed(), on_disk)

    def test_a_second_merge_lists_the_same(self):
        self.build_trees()
        self.merge()
        first = self.listed()
        self.merge()
        self.assertEqual(self.listed(), first)

    def test_the_feed_scope_manifest_reads_the_feed_copy(self):
        self.feed_trees()
        self.merge()
        doc = self.feed_rpm_manifest()
        self.assertEqual(sorted((p["name"], p["file"]) for p in doc["packages"]), [
            ("base-files", "%s/base-files-3.0.14-r0.1.%s.rpm" % (ARCH, ARCH)),
            ("kernel-%s" % L4T,
             "%s/kernel-%s-5.15.199+git0+abc-r0.1.%s.rpm" % (ARCH, L4T, ARCH)),
            ("nv-kernel-module-nvidia-%s" % L4T,
             "%s/nv-kernel-module-nvidia-%s-36.5.2-r0.3.%s.rpm" % (ARCH, L4T, ARCH)),
            (OOT, "%s/%s-36.5.2-r0.3.%s.rpm" % (ARCH, OOT, ARCH)),
        ])
        oot = next(p for p in doc["packages"] if p["name"] == OOT)
        # The header the feed serves, not the alternate tree's copy.
        self.assertIsNone(oot["epoch"])
        self.assertEqual(rpms.check_manifest(doc), [])

    def test_the_feed_scope_manifest_needs_the_merge_list(self):
        self.feed_trees()
        with self.assertRaises(Fatal) as caught:
            self.feed_rpm_manifest()
        self.assertIn("no list of the RPMs its merge published", str(caught.exception))

    def test_a_merge_that_fails_part_way_leaves_no_list(self):
        self.build_trees()
        self.merge()
        self.assertTrue(self.listed())
        # The second entry's copy fails after the first entry merged.
        os.remove(os.path.join(self.feed, ARCH,
                               "nv-kernel-module-nvidia-%s-36.5.2-r0.3.%s.rpm" % (L4T, ARCH)))
        os.chmod(os.path.join(self.feed, ARCH), 0o555)
        self.addCleanup(os.chmod, os.path.join(self.feed, ARCH), 0o755)
        result = self.merge(check=False)
        self.assertNotEqual(result.returncode, 0)
        with self.assertRaises(OSError):
            self.listed()

class Data:
    def __init__(self, **values):
        self.values = values
        self.flags = {}
        self.tasks = []

    def getVar(self, name):
        return self.values.get(name)

    def appendVarFlag(self, var, flag, value):
        self.flags[(var, flag)] = self.flags.get((var, flag), "") + value

    def setVarFlag(self, var, flag, value):
        self.flags[(var, flag)] = value

class MergeOrderTests(unittest.TestCase):
    """The feed tasks wait for the merge whose list the RPM manifest reads."""

    def run_anonymous(self, **values):
        with open(REPORT_BB) as f:
            text = f.read()
        m = re.search(r"^python \(\) \{\n(.*?)^\}", text, re.M | re.S)
        d = Data(**values)

        def fatal(msg):
            raise Fatal(msg)
        bb = types.SimpleNamespace(fatal=fatal, build=types.SimpleNamespace(
            addtask=lambda task, before, after, d: d.tasks.append((task, before, after)),
            deltask=lambda task, d: d.tasks.append(("deleted", task))))
        ns = {}
        exec("def run(d, bb):\n" + textwrap.indent(textwrap.dedent(m.group(1)), "    "), ns)
        ns["run"](d, bb)
        return d

    def test_feed_scope_on_a_multi_kernel_machine_reruns_the_merge(self):
        d = self.run_anonymous(AVOCADO_CVE_SCOPE="feed", AVOCADO_MULTIKERNEL_MC_RECIPES=MC_RECIPES)
        self.assertEqual(d.flags[("do_feed_sbom", "depends")],
                         " avocado-distro:do_multikernel_merge")
        self.assertIn(("deleted", "do_rm_work_all"), d.tasks)

    def test_a_single_kernel_feed_leaves_the_merge_alone(self):
        d = self.run_anonymous(AVOCADO_CVE_SCOPE="feed")
        self.assertNotIn(("do_feed_sbom", "depends"), d.flags)
        self.assertNotIn(("deleted", "do_rm_work_all"), d.tasks)

    def test_image_scope_leaves_the_merge_alone(self):
        d = self.run_anonymous(AVOCADO_CVE_SCOPE="image", AVOCADO_CVE_IMAGE="x",
                               AVOCADO_MULTIKERNEL_MC_RECIPES=MC_RECIPES)
        self.assertNotIn(("do_feed_sbom", "depends"), d.flags)
        self.assertEqual(d.tasks, [])

if __name__ == "__main__":
    unittest.main()
