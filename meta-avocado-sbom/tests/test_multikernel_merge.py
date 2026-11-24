#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""do_multikernel_merge publishes, and lists, exactly the alternate kernel's RPMs.

Runs avocado-multikernel.bbclass's do_multikernel_merge under bash, against a
fake pair of deploy trees, then reads the list it wrote. The RPM manifest does
not read that list (it covers the default multiconfig only, as the report
does), so the list is read here directly.

  python3 -m unittest discover -s meta-avocado-sbom/tests -p 'test_*.py'
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
sys.path.insert(0, HERE)

from test_rpms import rpm_bytes  # noqa: E402

BBCLASS = os.path.join(HERE, "..", "..", "meta-avocado", "classes",
                       "avocado-multikernel.bbclass")
MC = "jetson-l4t"
ARCH = "armv8a"
L4T = "5.15.199-l4t-r36.5"

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
        # Raises OSError when the merge left no list. The class spells the path.
        path = os.path.join(self.deploy, "avocado-multikernel", "%s-rpms.txt" % MC)
        with open(path) as f:
            return {line.strip() for line in f if line.strip()}

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


if __name__ == "__main__":
    unittest.main()
