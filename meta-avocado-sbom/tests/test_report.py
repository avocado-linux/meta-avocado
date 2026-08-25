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

from avocado_sbom.report import (  # noqa: E402
    SCOPES,
    Stats,
    build_report,
    read_cve_data,
    read_manifests,
    read_optouts,
)

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

    def read(self, recipe_versions, status="Unpatched"):
        return read_cve_data(
            self.cve_dir, recipe_versions, self.stats, status=status
        )

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

    def test_a_recipe_carrying_cves_is_not_a_no_record_recipe(self):
        # cve-check.bbclass skips the products of a CVE it ignored or found
        # already patched, so a recipe whose every record was patched is
        # written cvesInRecord "No" while its issues survive. At "Patched" that
        # recipe reports CVEs, and a recipe in "recipes" is in no other leg of
        # the partition.
        self.write("openssl", entry(
            "openssl", in_record="No",
            issues=[{"id": "CVE-2026-0001", "status": "Patched"}]))
        recipes, scanned, no_record = self.read(
            {"openssl": {"1.0"}}, status="Patched")
        self.assertIn("openssl", recipes)
        self.assertIn("openssl", scanned)
        self.assertNotIn("openssl", no_record)

    def test_no_record_survives_when_the_recipe_reports_nothing(self):
        # The same entry read at the default status carries no issue, so
        # nothing displaces it: the subtraction must not swallow the whole list.
        self.write("openssl", entry(
            "openssl", in_record="No",
            issues=[{"id": "CVE-2026-0001", "status": "Patched"}]))
        recipes, _, no_record = self.read({"openssl": {"1.0"}})
        self.assertNotIn("openssl", recipes)
        self.assertIn("openssl", no_record)

    def test_an_id_repeated_inside_one_entry_is_one_cve(self):
        issue = {"id": "CVE-2026-0001", "status": "Unpatched"}
        self.write("openssl", entry("openssl", issues=[issue, dict(issue)]))
        recipes, _, _ = self.read({"openssl": {"1.0"}})
        self.assertEqual(len(recipes["openssl"]["cves"]), 1)
        self.assertEqual(self.stats.cves, 1)

    def test_two_versions_merge_under_the_first_and_keep_both_cves(self):
        # Only reachable unpackaged: a packaged recipe has a known version and
        # anything else was dropped as stale. The first entry's version stands,
        # first meaning sorted filename then file order.
        self.write(
            "openssl",
            entry("openssl", version="1.0",
                  issues=[{"id": "CVE-2026-0001", "status": "Unpatched"}]),
            entry("openssl", version="2.0",
                  issues=[{"id": "CVE-2026-0002", "status": "Unpatched"}]),
        )
        recipes, _, _ = self.read({})
        self.assertEqual(recipes["openssl"]["version"], "1.0")
        self.assertEqual(
            sorted(c["id"] for c in recipes["openssl"]["cves"]),
            ["CVE-2026-0001", "CVE-2026-0002"],
        )
        self.assertEqual(self.stats.cves, 2)

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

    def test_the_partition_holds_at_a_patched_status(self):
        # The shape a "Patched" build hits: every record for the product was
        # already patched, so cve-check writes cvesInRecord "No" and the recipe
        # still reports a CVE. It belongs to "recipes" and to nothing else.
        self.package("libssl3", "openssl")
        self.package("pg-base", "packagegroup-base")
        self.write("openssl", entry(
            "openssl", in_record="No",
            issues=[{"id": "CVE-2026-1", "status": "Patched"}]))

        doc, _ = build_report(self.cve_dir, [self.pkgdata], status="Patched")
        unscanned = set(doc["unscanned_recipes"])
        no_record = set(doc["no_cve_record_recipes"])
        shipped = {p["recipe"] for p in doc["packages"].values()}

        self.assertIn("openssl", doc["recipes"])
        self.assertEqual(no_record, set())
        self.assertEqual(unscanned, {"packagegroup-base"})
        clean = shipped - unscanned - no_record - set(doc["recipes"])
        self.assertEqual(
            len(unscanned) + len(no_record) + len(clean) + len(doc["recipes"]),
            len(shipped),
        )
        self.assertEqual(doc["counts"]["no_cve_record_recipes"], 0)

    def test_counters_match_the_lists(self):
        self.package("libattr1", "attr")
        self.package("pg-base", "packagegroup-base")
        self.write("attr", entry("attr", in_record="No"))

        doc, stats = build_report(self.cve_dir, [self.pkgdata])
        self.assertEqual(doc["counts"]["unscanned_recipes"], 1)
        self.assertEqual(doc["counts"]["no_cve_record_recipes"], 1)
        self.assertEqual(stats.unscanned_recipes, 1)
        self.assertEqual(stats.no_cve_record_recipes, 1)

class ScopeTests(unittest.TestCase):
    """Scope labels a finding; it never filters the report."""

    def setUp(self):
        self.cve_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.cve_dir)
        self.pkgdata = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.pkgdata)
        os.makedirs(os.path.join(self.pkgdata, "runtime-reverse"))
        self.images = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.images)

    def package(self, name, recipe, version="1.0"):
        path = os.path.join(self.pkgdata, "runtime-reverse", name)
        with open(path, "w") as f:
            f.write("PN: %s\nPV: %s\nPKGV: %s\nPKGR: r0\n" % (recipe, version, version))

    def write(self, recipe, *entries):
        path = os.path.join(self.cve_dir, "%s_cve.json" % recipe)
        with open(path, "w") as f:
            json.dump({"package": list(entries)}, f)

    def manifest(self, name, *packages):
        path = os.path.join(self.images, "%s.manifest" % name)
        with open(path, "w") as f:
            for pkg in packages:
                f.write("%s cortexa57 1.0-r0\n" % pkg)
        return path

    def build(self, **kw):
        return build_report(self.cve_dir, [self.pkgdata], **kw)

    def populate(self):
        """One recipe per scope, all four carrying an Unpatched CVE."""
        cve = [{"id": "CVE-2026-1", "status": "Unpatched"}]
        self.package("libssl3", "openssl")      # installed -> base-runtime
        self.package("perl", "perl")            # built, not installed -> feed
        self.package("u-boot", "u-boot")        # declared boot chain
        self.write("openssl", entry("openssl", issues=cve))
        self.write("perl", entry("perl", issues=cve))
        self.write("u-boot", entry("u-boot", issues=cve))
        # No package in pkgdata at all -> build-only.
        self.write("go-cross-cortexa57", entry("go-cross-cortexa57", issues=cve))

    def test_every_scope_is_reachable_and_labelled(self):
        self.populate()
        doc, _ = self.build(
            manifest_paths=[self.manifest("rootfs", "libssl3")],
            boot_chain=["u-boot"],
        )
        scopes = {n: e["scope"] for n, e in doc["recipes"].items()}
        self.assertEqual(scopes, {
            "openssl": "base-runtime",
            "perl": "feed",
            "u-boot": "boot-chain",
            "go-cross-cortexa57": "build-only",
        })
        self.assertEqual(set(scopes.values()), set(SCOPES))

    def test_the_boot_chain_is_scoped_without_appearing_in_any_manifest(self):
        # u-boot reaches the device through avocado-img-bootfiles, which
        # scrapes DEPLOY_DIR_IMAGE, so no manifest names it. A scope keyed on
        # manifest membership would file the bootloader as feed and an
        # image-scoped report would drop it outright.
        self.populate()
        doc, _ = self.build(
            manifest_paths=[self.manifest("rootfs", "libssl3")],
            boot_chain=["u-boot"],
        )
        installed = read_manifests([self.manifest("rootfs", "libssl3")], Stats())
        self.assertNotIn("u-boot", installed)
        self.assertEqual(doc["recipes"]["u-boot"]["scope"], "boot-chain")
        self.assertTrue(doc["recipes"]["u-boot"]["packaged"])

    def test_a_deploy_only_recipe_is_not_called_build_only(self):
        """imx-atf and friends produce no package and run on the device, so
        the one value asserting a recipe is absent must not catch them.
        Naming each in AVOCADO_CVE_BOOT_CHAIN is no fix: a vendor layer adds
        recipes the default has never heard of, and the mislabel is silent.
        """
        cve = [{"id": "CVE-2026-1", "status": "Unpatched"}]
        for recipe in ("imx-atf", "imx-boot", "firmware-imx", "u-boot-imx"):
            self.write(recipe, entry(recipe, issues=cve))
        # -source and -initial are toolchain internals that match none of the
        # obvious suffixes; both scoped boot-chain on a real build.
        for recipe in ("go-cross-cortexa57", "expat-native", "gcc-cross",
                       "nativesdk-cmake", "binutils-cross-aarch64",
                       "gcc-source-13.4.0", "libgcc-initial", "glibc-initial"):
            self.write(recipe, entry(recipe, issues=cve))

        doc, _ = self.build(boot_chain=["u-boot", "trusted-firmware-a"])
        scopes = {n: e["scope"] for n, e in doc["recipes"].items()}

        for recipe in ("imx-atf", "imx-boot", "firmware-imx", "u-boot-imx"):
            self.assertEqual(scopes[recipe], "boot-chain", recipe)
        for recipe in ("go-cross-cortexa57", "expat-native", "gcc-cross",
                       "nativesdk-cmake", "binutils-cross-aarch64",
                       "gcc-source-13.4.0", "libgcc-initial", "glibc-initial"):
            self.assertEqual(scopes[recipe], "build-only", recipe)

    def test_scope_totals_are_derivable_from_the_entries(self):
        # Deliberately not counters. Every entry carries its own scope, so an
        # aggregate is one pass and cannot drift from what it summarises.
        self.populate()
        doc, _ = self.build(
            manifest_paths=[self.manifest("rootfs", "libssl3")],
            boot_chain=["u-boot"],
        )
        self.assertEqual(doc["counts"]["manifests_read"], 1)

        by_scope = {}
        for entry_ in doc["recipes"].values():
            by_scope[entry_["scope"]] = by_scope.get(entry_["scope"], 0) + 1
        self.assertEqual(by_scope, {
            "base-runtime": 1, "feed": 1, "boot-chain": 1, "build-only": 1,
        })
        self.assertEqual(sum(by_scope.values()), doc["counts"]["recipes"])

    def test_a_manifest_that_names_nothing_is_not_counted_as_read(self):
        # A truncated manifest would otherwise report the image as scoped
        # while scoping nothing, which is the silent-data-loss shape the
        # health counters exist to prevent.
        self.populate()
        empty = os.path.join(self.images, "truncated.manifest")
        open(empty, "w").close()
        doc, _ = self.build(manifest_paths=[empty], boot_chain=["u-boot"])
        self.assertEqual(doc["counts"]["manifests_read"], 0)
        self.assertEqual(doc["recipes"]["openssl"]["scope"], "feed")

    def test_the_coverage_denominator_does_not_move(self):
        """ENG-2200 criterion 3: scope is a field, not a filter, so reading a
        manifest must leave both coverage lists exactly as they were.
        """
        self.populate()
        self.package("libattr1", "attr")
        self.package("pg-base", "packagegroup-base")   # no file -> unscanned
        self.write("attr", entry("attr", in_record="No"))

        wide, _ = self.build()
        scoped, _ = self.build(
            manifest_paths=[self.manifest("rootfs", "libssl3")],
            boot_chain=["u-boot"],
        )

        for key in ("unscanned_recipes", "no_cve_record_recipes"):
            self.assertEqual(wide[key], scoped[key])
            self.assertEqual(wide["counts"][key], scoped["counts"][key])
        # And the findings themselves are the same set - nothing was filtered.
        self.assertEqual(set(wide["recipes"]), set(scoped["recipes"]))
        self.assertEqual(wide["counts"]["packages"], scoped["counts"]["packages"])
        self.assertEqual(wide["packages_digest"], scoped["packages_digest"])

    def test_without_a_manifest_everything_packaged_reads_feed(self):
        # The degradation when do_cve_report runs before the image tasks. It
        # must over-report the device's surface, never under-report it.
        self.populate()
        doc, _ = self.build(boot_chain=["u-boot"])
        self.assertEqual(doc["counts"]["manifests_read"], 0)
        self.assertNotIn(
            "base-runtime", {e["scope"] for e in doc["recipes"].values()}
        )
        self.assertEqual(doc["recipes"]["openssl"]["scope"], "feed")
        # The boot chain is declared, not measured, so it survives.
        self.assertEqual(doc["recipes"]["u-boot"]["scope"], "boot-chain")

    def test_an_unreadable_manifest_is_not_counted_and_does_not_raise(self):
        self.populate()
        doc, _ = self.build(
            manifest_paths=[os.path.join(self.images, "absent.manifest")],
        )
        self.assertEqual(doc["counts"]["manifests_read"], 0)

    def test_manifests_parse_to_package_names(self):
        stats = Stats()
        path = self.manifest("rootfs", "libssl3", "busybox")
        with open(path, "a") as f:
            f.write("\n")   # blank lines are ordinary in a manifest
        self.assertEqual(
            read_manifests([path], stats), {"libssl3", "busybox"}
        )
        self.assertEqual(stats.manifests_read, 1)

class ReadOptoutsTests(unittest.TestCase):
    """The markers avocado-cve-optout.bbclass leaves beside the cve-check
    results. They are what replaced a declared count, so a marker that reads
    wrong has to be counted, never silently dropped: an unreadable one makes
    the recipe it speaks for look like a scan that disappeared.
    """

    def setUp(self):
        self.cve_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.cve_dir)

    def write(self, name, data, suffix="_optout.json"):
        path = os.path.join(self.cve_dir, name + suffix)
        with open(path, "w") as f:
            if isinstance(data, str):
                f.write(data)
            else:
                json.dump(data, f)
        return path

    def marker(self, name, reason="CVE_PRODUCT is empty"):
        return {"version": "1", "name": name, "reason": reason}

    def test_a_marker_is_read(self):
        self.write("glibc-locale", self.marker("glibc-locale"))
        declared, unreadable = read_optouts(self.cve_dir)
        self.assertEqual(declared, {"glibc-locale": "CVE_PRODUCT is empty"})
        self.assertEqual(unreadable, 0)

    def test_the_reason_is_carried(self):
        self.write("foo", self.marker("foo", "PN is in CVE_CHECK_SKIP_RECIPE"))
        declared, _ = read_optouts(self.cve_dir)
        self.assertEqual(declared["foo"], "PN is in CVE_CHECK_SKIP_RECIPE")

    def test_the_name_inside_wins_over_the_filename(self):
        # The filename is ${PN}_optout.json, but PN is what the check joins on.
        self.write("whatever", self.marker("real-recipe-name"))
        declared, _ = read_optouts(self.cve_dir)
        self.assertEqual(list(declared), ["real-recipe-name"])

    def test_cve_results_are_not_mistaken_for_markers(self):
        self.write("acl", {"version": "1", "package": []}, suffix="_cve.json")
        self.assertEqual(read_optouts(self.cve_dir), ({}, 0))

    def test_an_empty_directory_declares_nothing(self):
        self.assertEqual(read_optouts(self.cve_dir), ({}, 0))

    def test_a_missing_directory_does_not_raise(self):
        self.assertEqual(
            read_optouts(os.path.join(self.cve_dir, "nope")), ({}, 0)
        )

    def test_truncated_json_is_counted_not_dropped(self):
        self.write("half", '{"version": "1", "name": "ha')
        declared, unreadable = read_optouts(self.cve_dir)
        self.assertEqual(declared, {})
        self.assertEqual(unreadable, 1)

    def test_a_marker_missing_its_fields_is_counted(self):
        self.write("noname", {"version": "1", "reason": "CVE_PRODUCT is empty"})
        self.write("noreason", {"version": "1", "name": "noreason"})
        self.write("notadict", [1, 2, 3])
        declared, unreadable = read_optouts(self.cve_dir)
        self.assertEqual(declared, {})
        self.assertEqual(unreadable, 3)

    def test_a_bad_marker_does_not_hide_a_good_one(self):
        self.write("good", self.marker("good"))
        self.write("bad", "not json at all")
        declared, unreadable = read_optouts(self.cve_dir)
        self.assertEqual(list(declared), ["good"])
        self.assertEqual(unreadable, 1)

if __name__ == "__main__":
    unittest.main()
