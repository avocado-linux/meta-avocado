#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""The RPM manifest lists exactly the alternate-kernel RPMs the merge published.

Runs avocado-multikernel.bbclass's do_multikernel_merge under bash, against a
fake pair of deploy trees, then builds the manifest from the list it wrote: with
rpms.build_manifest, and at feed scope with avocado-cve-report's own
do_rpm_manifest.

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

BBCLASS = os.path.join(HERE, "..", "..", "meta-avocado", "classes",
                       "avocado-multikernel.bbclass")
REPORT_BB = os.path.join(HERE, "..", "recipes-avocado", "avocado-cve-report",
                         "avocado-cve-report.bb")
MC = "jetson-l4t"
ARCH = "armv8a"
L4T = "5.15.199-l4t-r36.5"
MACHINE = "avocado-jetson-orin-nx"

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
        self.alt_rpm = os.path.join(self.top, "tmp-%s" % MC, "deploy", "rpm")
        self.feed = os.path.join(self.deploy, "rpm")
        os.makedirs(self.feed)

    def rpm(self, rpm_dir, name, version, release="r0.1", arch=ARCH):
        path = os.path.join(rpm_dir, arch, "%s-%s-%s.%s.rpm" % (name, version, release, arch))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(rpm_bytes(name, version, release, arch))

    def merge(self, cve_dir="", check=True):
        # bitbake substitutes these datastore variables; plain shell variables
        # of the same names stand in for them.
        script = "\n".join([
            "set -e",
            "bbnote() { :; }",
            "bbfatal() { echo \"ERROR: $*\" >&2; exit 1; }",
            'AVOCADO_MULTIKERNEL_MC_RECIPES="%s:linux-jammy-nvidia-tegra %s:nvidia-kernel-oot"'
            % (MC, MC),
            'TOPDIR="%s"' % self.top,
            'DEPLOY_DIR="%s"' % self.deploy,
            'CVE_CHECK_DIR="%s"' % cve_dir,
            'DEPLOY_DIR_SPDX=""',
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

    def feed_rpm_manifest(self):
        out = os.path.join(self.deploy, "avocado-cve", "avocado-rpm-manifest.json")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        tmp = os.path.join(self.top, "tmp")
        report_rpm_manifest({
            "AVOCADO_CVE_SCOPE": "feed", "MACHINE": MACHINE, "DISTRO_VERSION": "2024.1",
            "TOPDIR": self.top, "TMPDIR": tmp, "DEPLOY_DIR": self.deploy,
            "DEPLOY_DIR_RPM": self.feed,
            "PKGDATA_DIR": os.path.join(tmp, "pkgdata", "jetson"),
            "AVOCADO_RPM_MANIFEST_FILE": out,
            "AVOCADO_MULTIKERNEL_MC_RECIPES":
                "%s:linux-jammy-nvidia-tegra %s:nvidia-kernel-oot" % (MC, MC),
        })
        with open(out) as f:
            return json.load(f)

    def feed_trees(self):
        self.build_alt_tree()
        self.rpm(self.feed, "base-files", "3.0.14")
        self.pkgdata("tmp", "base-files", {"base-files": ("3.0.14", "r0.1")})
        alt = "tmp-%s" % MC
        self.pkgdata(alt, "linux-jammy-nvidia-tegra",
                     {"kernel-%s" % L4T: ("5.15.199+git0+abc", "r0.1")})
        self.pkgdata(alt, "nvidia-kernel-oot",
                     {"nv-kernel-module-nvidia-%s" % L4T: ("36.5.2", "r0.3"),
                      "nvidia-kernel-oot": ("36.5.2", "r0.3")})
        # Built in the alternate tree, not one of its feed recipes.
        self.pkgdata(alt, "base-files", {"base-files": ("3.0.14", "r0.1")})

    def test_the_feed_scope_manifest_lists_what_the_merge_published(self):
        self.feed_trees()
        self.merge()
        doc = self.feed_rpm_manifest()
        self.assertEqual(sorted((p["name"], p["file"]) for p in doc["packages"]), [
            ("base-files", "%s/base-files-3.0.14-r0.1.%s.rpm" % (ARCH, ARCH)),
            ("kernel-%s" % L4T,
             "%s/kernel-%s-5.15.199+git0+abc-r0.1.%s.rpm" % (ARCH, L4T, ARCH)),
            ("nv-kernel-module-nvidia-%s" % L4T,
             "%s/nv-kernel-module-nvidia-%s-36.5.2-r0.3.%s.rpm" % (ARCH, L4T, ARCH)),
        ])

    def test_the_feed_scope_manifest_needs_the_merge_list(self):
        self.feed_trees()
        with self.assertRaises(Fatal) as caught:
            self.feed_rpm_manifest()
        self.assertIn("no list of the RPMs its merge published", str(caught.exception))

    def build_alt_tree(self):
        self.rpm(self.alt_rpm, "kernel-%s" % L4T, "5.15.199+git0+abc")
        self.rpm(self.alt_rpm, "nv-kernel-module-nvidia-%s" % L4T, "36.5.2", "r0.3")
        # Unversioned names: built in the alt tree, never merged.
        self.rpm(self.alt_rpm, "nvidia-kernel-oot", "36.5.2", "r0.3")
        self.rpm(self.alt_rpm, "base-files", "3.0.14")

    def test_the_list_is_what_the_feed_received(self):
        self.build_alt_tree()
        self.merge()
        on_disk = {os.path.relpath(os.path.join(root, f), self.feed)
                   for root, _dirs, files in os.walk(self.feed) for f in files}
        self.assertEqual(self.listed(), on_disk)
        self.assertEqual(self.listed(), {
            "%s/kernel-%s-5.15.199+git0+abc-r0.1.%s.rpm" % (ARCH, L4T, ARCH),
            "%s/nv-kernel-module-nvidia-%s-36.5.2-r0.3.%s.rpm" % (ARCH, L4T, ARCH),
        })

    def test_a_file_already_in_the_feed_is_still_listed(self):
        self.build_alt_tree()
        self.merge()
        self.merge()
        self.assertEqual(len(self.listed()), 2)

    def test_a_merge_with_no_alt_kernel_fails_and_leaves_no_list(self):
        self.build_alt_tree()
        self.merge()
        shutil.rmtree(self.alt_rpm)
        self.rpm(self.alt_rpm, "base-files", "3.0.14")
        result = self.merge(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("could not derive a kernel version", result.stderr)
        with self.assertRaises(OSError):
            self.listed()

    def test_a_merge_that_fails_part_way_leaves_no_list(self):
        # A failed evidence copy, in the first entry (before any RPM merge) or
        # the second (after the first entry for the same multiconfig merged
        # its RPMs), on top of a list a previous merge left.
        for failing in ("linux-jammy-nvidia-tegra", "nvidia-kernel-oot"):
            with self.subTest(failing=failing):
                self.setUp()
                self.build_alt_tree()
                self.merge()
                self.assertTrue(self.listed())
                alt_cve = os.path.join(self.top, "tmp-%s" % MC, "deploy", "cve")
                os.makedirs(alt_cve)
                for recipe in ("linux-jammy-nvidia-tegra", "nvidia-kernel-oot"):
                    with open(os.path.join(alt_cve, recipe + "_cve.json"), "w") as f:
                        f.write("{}")
                unreadable = os.path.join(alt_cve, failing + "_cve.json")
                os.chmod(unreadable, 0)
                self.addCleanup(os.chmod, unreadable, 0o644)
                result = self.merge(cve_dir=os.path.join(self.deploy, "cve"), check=False)
                self.assertIn("%s_cve.json" % failing, result.stderr)
                self.assertNotEqual(result.returncode, 0)
                with self.assertRaises(OSError):
                    self.listed()

    def test_the_manifest_leaves_out_what_the_merge_did_not_publish(self):
        self.build_alt_tree()
        self.rpm(self.feed, "kernel-6.6", "6.6.111", "r0.1")
        self.merge()

        def pkgdata(names):
            return {n: {"recipe": "x", "version": v, "origin": "x"}
                    for n, v in names.items()}

        alt = pkgdata({
            "kernel-%s" % L4T: "5.15.199-git0-abc-r0.1",
            "nv-kernel-module-nvidia-%s" % L4T: "36.5.2-r0.3",
            "nvidia-kernel-oot": "36.5.2-r0.3",
            "base-files": "3.0.14-r0.1",
        })
        doc = rpms.build_manifest(
            [(pkgdata({"kernel-6.6": "6.6.111-r0.1"}), self.feed),
             (alt, self.feed, self.listed())],
            machine="avocado-test")
        self.assertEqual(sorted(p["name"] for p in doc["packages"]),
                         ["kernel-%s" % L4T, "kernel-6.6",
                          "nv-kernel-module-nvidia-%s" % L4T])
        self.assertEqual(rpms.check_manifest(doc), [])

if __name__ == "__main__":
    unittest.main()
