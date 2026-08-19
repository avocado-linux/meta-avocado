#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""Prove what unscanned_recipes and no_cve_record_recipes each mean.

The two are easy to conflate - both describe a recipe absent from "recipes" -
and conflating them is the defect this file exists to prevent: a recipe
cve-check looked up and found no NVD record for was once reported as unscanned,
which is the opposite of the truth.

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

from avocado_sbom.report import Stats, build_report, read_cve_data  # noqa: E402

def entry(name, version="1.0", in_record="Yes", issues=(), products=None):
    if products is None:
        products = [{"product": name, "cvesInRecord": in_record}]
    return {
        "name": name,
        "version": version,
        "products": products,
        "issue": list(issues),
    }

class ReadCveDataTests(unittest.TestCase):
    def setUp(self):
        self.cve_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.cve_dir)
        self.stats = Stats()

    def write(self, recipe, *entries):
        path = os.path.join(self.cve_dir, "%s_cve.json" % recipe)
        with open(path, "w") as f:
            json.dump({"package": list(entries)}, f)

    def read(self, recipe_versions):
        return read_cve_data(self.cve_dir, recipe_versions, self.stats)

    def test_no_nvd_record_is_scanned_not_unscanned(self):
        # The defect: cvesInRecord "No" means cve-check looked the product up
        # and the database had nothing, which is the strongest evidence a
        # recipe was scanned.
        self.write("attr", entry("attr", in_record="No"))
        _, scanned, no_record = self.read({"attr": {"1.0"}})
        self.assertIn("attr", scanned)
        self.assertIn("attr", no_record)

    def test_a_recipe_with_a_record_is_not_in_no_cve_record(self):
        self.write("openssl", entry("openssl"))
        _, scanned, no_record = self.read({"openssl": {"1.0"}})
        self.assertIn("openssl", scanned)
        self.assertNotIn("openssl", no_record)

    def test_one_product_with_a_record_is_enough(self):
        # Order must not decide it: a recipe whose entries are split across
        # products is a no-record recipe only when every product is.
        self.write(
            "multi",
            entry("multi", products=[{"product": "a", "cvesInRecord": "No"}]),
            entry("multi", products=[{"product": "b", "cvesInRecord": "Yes"}]),
        )
        _, _, no_record = self.read({"multi": {"1.0"}})
        self.assertNotIn("multi", no_record)

    def test_a_stale_version_still_counts_as_scanned(self):
        # The entry is dropped because pkgdata built another version, but
        # something did look at the recipe.
        self.write("busybox", entry("busybox", version="9.9"))
        _, scanned, _ = self.read({"busybox": {"1.0"}})
        self.assertEqual(self.stats.stale_dropped, 1)
        self.assertIn("busybox", scanned)

    def test_a_recipe_with_no_file_is_not_scanned(self):
        self.write("openssl", entry("openssl"))
        _, scanned, _ = self.read({"openssl": {"1.0"}, "packagegroup-base": {"1.0"}})
        self.assertNotIn("packagegroup-base", scanned)

    def test_two_entries_for_one_recipe_keep_the_counters_honest(self):
        # Overwriting left stats holding the replaced entry's CVEs, and counts
        # that exceed the document fail the contract check as malformed - the
        # one verdict no setting overrides.
        self.write(
            "openssl",
            entry("openssl", issues=[{"id": "CVE-2026-0001",
                                      "status": "Unpatched"}]),
            entry("openssl", issues=[{"id": "CVE-2026-0002",
                                      "status": "Unpatched"}]),
        )
        recipes, _, _ = self.read({"openssl": {"1.0"}})
        self.assertEqual(len(recipes), 1)
        self.assertEqual(
            self.stats.cves, sum(len(e["cves"]) for e in recipes.values())
        )
        self.assertEqual(self.stats.packaged_recipes, 1)
        self.assertEqual(self.stats.packaged_cves, self.stats.cves)

    def test_the_same_cve_twice_is_one_cve(self):
        issue = {"id": "CVE-2026-0001", "status": "Unpatched"}
        self.write("openssl", entry("openssl", issues=[issue]),
                   entry("openssl", issues=[issue]))
        recipes, _, _ = self.read({"openssl": {"1.0"}})
        self.assertEqual(len(recipes["openssl"]["cves"]), 1)
        self.assertEqual(self.stats.cves, 1)

    def test_a_merged_entry_keeps_both_recipes_cves(self):
        self.write(
            "openssl",
            entry("openssl", issues=[{"id": "CVE-2026-0001",
                                      "status": "Unpatched"}]),
            entry("openssl", issues=[{"id": "CVE-2026-0002",
                                      "status": "Unpatched"}]),
        )
        recipes, _, _ = self.read({"openssl": {"1.0"}})
        self.assertEqual(
            sorted(c["id"] for c in recipes["openssl"]["cves"]),
            ["CVE-2026-0001", "CVE-2026-0002"],
        )

class BuildReportTests(unittest.TestCase):
    """The two lists partition the shipped recipes with the clean ones."""

    def setUp(self):
        self.cve_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.cve_dir)
        self.pkgdata = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.pkgdata)
        os.makedirs(os.path.join(self.pkgdata, "runtime-reverse"))

    def package(self, name, recipe, version="1.0"):
        path = os.path.join(self.pkgdata, "runtime-reverse", name)
        with open(path, "w") as f:
            f.write("PN: %s\nPV: %s\nPKGV: %s\nPKGR: r0\n" % (recipe, version, version))

    def write(self, recipe, *entries):
        path = os.path.join(self.cve_dir, "%s_cve.json" % recipe)
        with open(path, "w") as f:
            json.dump({"package": list(entries)}, f)

    def test_lists_are_disjoint_and_scoped_to_shipped_recipes(self):
        self.package("libssl3", "openssl")
        self.package("libattr1", "attr")
        self.package("pg-base", "packagegroup-base")
        self.package("libz1", "zlib")
        # openssl: scanned, has a record, one CVE.
        self.write("openssl", entry(
            "openssl", issues=[{"id": "CVE-2026-1", "status": "Unpatched"}]))
        # attr: scanned, no NVD record.
        self.write("attr", entry("attr", in_record="No"))
        # zlib: scanned, has a record, no CVEs at this status - clean.
        self.write("zlib", entry("zlib"))
        # packagegroup-base: no file at all - opted out.
        # quilt-native: scanned but ships nothing, so in neither list.
        self.write("quilt-native", entry("quilt-native", in_record="No"))

        doc, _ = build_report(self.cve_dir, [self.pkgdata])
        unscanned = set(doc["unscanned_recipes"])
        no_record = set(doc["no_cve_record_recipes"])

        self.assertEqual(unscanned, {"packagegroup-base"})
        self.assertEqual(no_record, {"attr"})
        self.assertEqual(unscanned & no_record, set())
        self.assertNotIn("quilt-native", unscanned | no_record)

        shipped = {p["recipe"] for p in doc["packages"].values()}
        clean = shipped - unscanned - no_record - set(doc["recipes"])
        self.assertEqual(clean, {"zlib"})
        self.assertEqual(
            len(unscanned) + len(no_record) + len(clean) + len(doc["recipes"]),
            len(shipped),
        )

    def test_counters_match_the_lists(self):
        self.package("libattr1", "attr")
        self.package("pg-base", "packagegroup-base")
        self.write("attr", entry("attr", in_record="No"))

        doc, stats = build_report(self.cve_dir, [self.pkgdata])
        self.assertEqual(doc["counts"]["unscanned_recipes"], 1)
        self.assertEqual(doc["counts"]["no_cve_record_recipes"], 1)
        self.assertEqual(stats.unscanned_recipes, 1)
        self.assertEqual(stats.no_cve_record_recipes, 1)

if __name__ == "__main__":
    unittest.main()
