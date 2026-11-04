#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""The RPM manifest read through real pkgdata, as do_rpm_manifest reads it.

test_rpms.py hands build_manifest() package maps directly. These go through
report.read_pkgdata() and rpms.read_package_sizes() on runtime-reverse files,
which is the join the recipe makes, and check the manifest against the report
built from the same pkgdata: the two are consumed as a pair. TaskTests also
take out the packages without an RPM first, as the task does.

  python3 -m unittest discover -s meta-avocado-sbom/tests -p 'test_*.py'
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
sys.path.insert(0, HERE)

from avocado_sbom import report, rpmless, rpms  # noqa: E402
from test_rpms import rpm_bytes  # noqa: E402

MACHINE = "avocado-test"

def manifest_packages(pkgdata_dir):
    """do_rpm_manifest's package map: read_pkgdata's, with PKGSIZE added."""
    sizes = rpms.read_package_sizes(pkgdata_dir)
    return {name: dict(info, size=sizes.get(name))
            for name, info in report.read_pkgdata([pkgdata_dir], report.Stats())[0].items()}

class PkgdataTree(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="avocado-rpms-pkgdata-test-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.pkgdata = os.path.join(self.tmp, "pkgdata", MACHINE)
        self.rpm_dir = os.path.join(self.tmp, "deploy", "rpm")
        os.makedirs(os.path.join(self.pkgdata, "runtime-reverse"))

    def package(self, name, lines):
        with open(os.path.join(self.pkgdata, "runtime-reverse", name), "w") as f:
            f.write("".join("%s\n" % line for line in lines))

    def rpm(self, name, version, release, arch="cortexa76"):
        path = os.path.join(self.rpm_dir, arch,
                            "%s-%s-%s.%s.rpm" % (name, version, release, arch))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(rpm_bytes(name, version, release, arch))

    def build(self):
        return rpms.build_manifest([(manifest_packages(self.pkgdata), self.rpm_dir)],
                                   machine=MACHINE)

    def build_as_task(self):
        """(manifest, dropped) the way do_rpm_manifest makes them."""
        packages, dropped = rpmless.drop_rpmless(manifest_packages(self.pkgdata),
                                                 self.rpm_dir)
        return (rpms.build_manifest([(packages, self.rpm_dir)], machine=MACHINE),
                dropped)

class PkgdataJoinTests(PkgdataTree):
    def test_a_package_with_its_own_pkgv_is_named_by_it(self):
        # lvm2's libdevmapper is 1.02.213 against lvm2's 2.03.39, and its
        # runtime-reverse file carries PKGV:libdevmapper and no plain PKGV.
        self.package("libdevmapper", ["PN: lvm2", "PV: 2.03.39",
                                      "PKGV:libdevmapper: 1.02.213",
                                      "PKGR:libdevmapper: r0.3",
                                      "PKGSIZE:libdevmapper: 400000"])
        self.rpm("libdevmapper", "1.02.213", "r0.3")
        entry = self.build()["packages"][0]
        self.assertEqual((entry["name"], entry["version"], entry["release"]),
                         ("libdevmapper", "1.02.213", "r0.3"))

    def test_an_empty_package_without_an_rpm_is_excused_through_pkgdata(self):
        self.package("avocado-core", ["PN: avocado-core", "PKGV: 1.0", "PKGR: r0.1",
                                      "PKGSIZE:avocado-core: 10"])
        self.package("avocado-core-dbg", ["PN: avocado-core", "PKGV: 1.0",
                                          "PKGR: r0.1", "PKGSIZE:avocado-core-dbg: 0"])
        self.rpm("avocado-core", "1.0", "r0.1")
        self.assertEqual([p["name"] for p in self.build()["packages"]], ["avocado-core"])

    def test_a_package_without_a_size_line_is_not_excused(self):
        # By build_manifest itself. The task takes it out first (TaskTests).
        self.package("foo", ["PN: foo", "PKGV: 1.0", "PKGR: r0.1"])
        self.package("bar", ["PN: bar", "PKGV: 1.0", "PKGR: r0.1"])
        self.rpm("bar", "1.0", "r0.1")
        with self.assertRaises(rpms.ManifestError) as caught:
            self.build()
        self.assertIn("foo", str(caught.exception))

class TaskTests(PkgdataTree):
    """do_rpm_manifest leaves out what has no RPM and fails on anything else."""

    def setUp(self):
        super().setUp()
        self.package("busybox", ["PN: busybox", "PKGV: 1.37.0", "PKGR: r0.2",
                                 "PKGSIZE:busybox: 700000"])
        self.rpm("busybox", "1.37.0", "r0.2")

    def test_a_package_with_a_size_and_no_rpm_is_left_out(self):
        # A build-time-only dependency at image scope: pkgdata names it, with
        # a size, and package_rpm never wrote it.
        self.package("libbuildonly", ["PN: buildonly", "PKGV: 0.26", "PKGR: r0.1",
                                      "PKGSIZE:libbuildonly: 5000"])
        manifest, dropped = self.build_as_task()
        self.assertEqual(dropped, ["libbuildonly"])
        self.assertEqual([p["name"] for p in manifest["packages"]], ["busybox"])
        self.assertEqual(rpms.check_manifest(manifest), [])
        scan = os.path.join(self.tmp, "world-recipe-sbom.sbom-cve-check.yocto.json")
        with open(scan, "w") as f:
            json.dump({"version": "1", "package": []}, f)
        doc, _stats = report.build_report([scan], [self.pkgdata],
                                          machine=MACHINE, status="All")
        for entry in manifest["packages"]:
            self.assertIn(entry["name"], doc["packages"])

    def test_a_package_without_a_size_line_and_no_rpm_is_left_out(self):
        self.package("foo", ["PN: foo", "PKGV: 1.0", "PKGR: r0.1"])
        manifest, dropped = self.build_as_task()
        self.assertEqual(dropped, ["foo"])
        self.assertEqual([p["name"] for p in manifest["packages"]], ["busybox"])

    def test_an_empty_package_is_still_excused_without_a_warning(self):
        self.package("busybox-dbg", ["PN: busybox", "PKGV: 1.37.0", "PKGR: r0.2",
                                     "PKGSIZE:busybox-dbg: 0"])
        manifest, dropped = self.build_as_task()
        self.assertEqual(dropped, [])
        self.assertEqual([p["name"] for p in manifest["packages"]], ["busybox"])

    def test_an_rpm_holding_another_package_still_fails(self):
        self.package("bar", ["PN: bar", "PKGV: 1.0", "PKGR: r0.1",
                             "PKGSIZE:bar: 10"])
        path = os.path.join(self.rpm_dir, "cortexa76", "bar-1.0-r0.1.cortexa76.rpm")
        with open(path, "wb") as f:
            f.write(rpm_bytes("baz", "1.0", "r0.1", "cortexa76"))
        with self.assertRaises(rpms.ManifestError) as caught:
            self.build_as_task()
        self.assertIn("holds a different package", str(caught.exception))

    def test_a_version_with_no_release_still_fails(self):
        self.package("qux", ["PN: qux", "PKGV: 1.0", "PKGSIZE:qux: 10"])
        with self.assertRaises(rpms.ManifestError) as caught:
            self.build_as_task()
        self.assertIn("qux", str(caught.exception))

class PairTests(PkgdataTree):
    """The manifest and the report of one build agree on what a consumer joins."""

    def setUp(self):
        super().setUp()
        self.package("busybox", ["PN: busybox", "PV: 1.37.0", "PKGV: 1.37.0",
                                 "PKGR: r0.2", "PKGSIZE:busybox: 700000"])
        self.package("libedit0", ["PN: libedit", "PV: 20250104-3.1",
                                  "PKGV: 20250104-3.1", "PKGR: r0.1",
                                  "PKGSIZE:libedit0: 200000"])
        self.rpm("busybox", "1.37.0", "r0.2")
        self.rpm("libedit0", "20250104+3.1", "r0.1")
        scan = os.path.join(self.tmp, "world-recipe-sbom.sbom-cve-check.yocto.json")
        with open(scan, "w") as f:
            json.dump({"version": "1", "package": []}, f)
        self.report, _stats = report.build_report([scan], [self.pkgdata],
                                                  machine=MACHINE, status="All")
        self.manifest = self.build()

    def test_every_listed_rpm_is_in_the_reports_packages(self):
        self.assertTrue(self.manifest["packages"])
        for entry in self.manifest["packages"]:
            self.assertIn(entry["name"], self.report["packages"])

    def test_both_name_the_same_machine(self):
        self.assertEqual(self.manifest["machine"], self.report["machine"])

    def test_the_manifest_passes_its_own_check(self):
        self.assertEqual(rpms.check_manifest(self.manifest), [])

if __name__ == "__main__":
    unittest.main()
