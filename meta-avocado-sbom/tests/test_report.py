#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""Prove what recipe_versions carries and why a rescan needs it.

  python3 -m unittest discover -s meta-avocado-sbom/tests -p 'test_*.py'
"""

import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

from avocado_sbom import report  # noqa: E402
from avocado_sbom.report import (  # noqa: E402
    MANIFEST_SUFFIX,
    Stats,
    build_report,
    read_cve_data,
)

def entry(name, version, *ids):
    return {
        "name": name,
        "version": version,
        "issue": [{"id": i, "status": "Unpatched"} for i in ids],
    }

class RecipeVersionsTests(unittest.TestCase):
    """The defect: a rescan matched manifest entries against the packages'
    PKGV-PKGR, so a recipe whose PV is not that (glibc 2.43+git, a +git
    kernel) was dropped as stale, 76 CVEs against the build's 5,332.
    """

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        self.pkgdata = os.path.join(self.root, "pkgdata")
        os.makedirs(os.path.join(self.pkgdata, "runtime-reverse"))
        self.manifest = os.path.join(self.root, "world" + MANIFEST_SUFFIX)

    def package(self, name, recipe, pv, pkgv):
        path = os.path.join(self.pkgdata, "runtime-reverse", name)
        with open(path, "w") as f:
            f.write("PN: %s\nPV: %s\nPKGV: %s\nPKGR: r0\n" % (recipe, pv, pkgv))

    def populate(self):
        self.package("libc6", "glibc", "2.43+git", "2.43+git1+562cd7badd")
        self.package("glibc-utils", "glibc", "2.43+git", "2.43+git0+562cd7badd")
        self.package("libssl3", "openssl", "3.5.7", "3.5.7")
        # Scanned clean: in the map all the same, or a later scan's first CVE
        # for it reads as unpackaged.
        self.package("libz1", "zlib", "1.3.1", "1.3.1")
        # No manifest entry at all this build; a later scan may have one.
        self.package("libattr1", "attr", "2.5.2", "2.5.2")
        # A package with its own version writes only PKGV:<package>, which no
        # manifest entry carries, so it stays out of the map.
        path = os.path.join(self.pkgdata, "runtime-reverse", "libdevmapper")
        with open(path, "w") as f:
            f.write("PN: lvm2\nPV: 2.03.39\nPKGV:libdevmapper: 1.02.213\n"
                    "PKGR:libdevmapper: r0.3\n")
        with open(self.manifest, "w") as f:
            json.dump({"package": [
                entry("glibc", "2.43+git", "CVE-2026-1"),
                entry("openssl", "3.5.7", "CVE-2026-2"),
                entry("zlib", "1.3.1"),
            ]}, f)

    def build(self):
        return build_report([self.manifest], [self.pkgdata])[0]

    def test_every_pkgdata_version_is_listed_sorted(self):
        self.populate()
        doc = self.build()
        self.assertEqual(doc["recipe_versions"], {
            "attr": ["2.5.2"],
            "glibc": ["2.43+git", "2.43+git0+562cd7badd", "2.43+git1+562cd7badd"],
            "lvm2": ["2.03.39"],
            "openssl": ["3.5.7"],
            "zlib": ["1.3.1"],
        })
        self.assertIn("attr", doc["unscanned_recipes"])
        self.assertNotIn("zlib", doc["recipes"])
        self.assertEqual(doc["packages"]["libdevmapper"]["version"], "1.02.213-r0.3")

    def test_the_lists_are_sorted_whatever_order_pkgdata_gives(self):
        self.populate()
        read = report.read_pkgdata

        def reversed_sets(*args):
            packages, versions = read(*args)
            return packages, {n: sorted(v, reverse=True) for n, v in versions.items()}

        with mock.patch.object(report, "read_pkgdata", reversed_sets):
            doc = self.build()
        self.assertEqual(doc["recipe_versions"]["glibc"],
                         ["2.43+git", "2.43+git0+562cd7badd", "2.43+git1+562cd7badd"])

    def test_the_document_is_deterministic(self):
        self.populate()
        first, second = self.build(), self.build()
        for doc in (first, second):
            del doc["generated"]
        self.assertEqual(json.dumps(first, sort_keys=True),
                         json.dumps(second, sort_keys=True))

    def test_a_rescan_from_the_map_keeps_what_the_build_kept(self):
        self.populate()
        doc = self.build()

        from_map = Stats()
        recipes, _ = read_cve_data(
            [self.manifest],
            {n: set(v) for n, v in doc["recipe_versions"].items()},
            from_map)
        self.assertEqual(set(recipes), set(doc["recipes"]))
        self.assertEqual(from_map.stale_dropped, 0)

        # The control: the packages' own versions lose glibc.
        from_packages = Stats()
        package_versions = {}
        for pkg in doc["packages"].values():
            package_versions.setdefault(pkg["recipe"], set()).add(pkg["version"])
        recipes, _ = read_cve_data([self.manifest], package_versions, from_packages)
        self.assertNotIn("glibc", recipes)
        self.assertGreater(from_packages.stale_dropped, 0)

    def test_a_package_name_two_directories_claim_keeps_both_recipes(self):
        # The first pkgdata directory wins the name, but the loser's recipe
        # still matched its entry at build time, so the map carries it too.
        self.populate()
        sdk = os.path.join(self.root, "sdk")
        os.makedirs(os.path.join(sdk, "runtime-reverse"))
        with open(os.path.join(sdk, "runtime-reverse", "libssl3"), "w") as f:
            f.write("PN: openssl-vendor\nPV: 1.1.1w\nPKGV: 1.1.1w\nPKGR: r0\n")
        with open(self.manifest) as f:
            data = json.load(f)
        # Clean at build time, so nothing in "recipes" names it.
        data["package"].append(entry("openssl-vendor", "1.1.1w"))
        with open(self.manifest, "w") as f:
            json.dump(data, f)

        doc = build_report([self.manifest], [self.pkgdata, sdk])[0]
        self.assertEqual(doc["packages"]["libssl3"]["recipe"], "openssl")
        self.assertEqual(doc["recipe_versions"]["openssl-vendor"], ["1.1.1w"])
        self.assertNotIn("openssl-vendor", doc["recipes"])

        # Its first CVE, in a later scan.
        data["package"][-1] = entry("openssl-vendor", "1.1.1w", "CVE-2026-3")
        with open(self.manifest, "w") as f:
            json.dump(data, f)
        recipes, _ = read_cve_data(
            [self.manifest],
            {n: set(v) for n, v in doc["recipe_versions"].items()},
            Stats())
        self.assertIs(recipes["openssl-vendor"]["packaged"], True)

    def test_a_rescan_drops_a_stale_entry_for_a_recipe_never_scanned(self):
        self.populate()
        doc = self.build()
        with open(self.manifest, "w") as f:
            json.dump({"package": [entry("attr", "2.5.1", "CVE-2026-4")]}, f)
        stats = Stats()
        recipes, _ = read_cve_data(
            [self.manifest],
            {n: set(v) for n, v in doc["recipe_versions"].items()},
            stats)
        self.assertNotIn("attr", recipes)
        self.assertEqual(stats.stale_dropped, 1)

    def test_packages_digest_does_not_cover_it(self):
        self.populate()
        doc = self.build()
        digest = hashlib.sha256()
        for name in sorted(doc["packages"]):
            pkg = doc["packages"][name]
            digest.update(("%s\t%s\t%s\n" % (
                name, pkg["recipe"], pkg["version"])).encode())
        self.assertEqual(doc["packages_digest"], "sha256:" + digest.hexdigest())

if __name__ == "__main__":
    unittest.main()
