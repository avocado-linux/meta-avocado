#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""Prove the report fields a consumer binds package verdicts on: alt_versions
with recipe_version, no_cve_record_recipes, and the CVE_STATUS detail of an
Ignored CVE, each from a build tree and from a previous report.

  python3 -m unittest discover -s meta-avocado-sbom/tests -p 'test_*.py'
"""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

import binding_rules  # noqa: E402
from avocado_sbom import feedsbom, report  # noqa: E402
from avocado_sbom.report import (  # noqa: E402
    MANIFEST_SUFFIX,
    REPORT_STATUSES,
    build_report,
    build_report_from_anchor,
    write_report,
)

DEFAULT = "6.12.87+git"
ALT = "6.6.78+git"

def issue(cve, status="Unpatched", **extra):
    item = {"id": cve, "status": status, "summary": "s " + cve,
            "description": "d " + cve, "scorev3": "7.5", "link": "l"}
    item.update(extra)
    return item

def entry(name, version, *issues):
    return {"name": name, "version": version, "issue": list(issues)}

def round_trip(doc, root):
    path = os.path.join(root, "anchor.json")
    write_report(doc, path)
    with open(path) as f:
        return json.load(f)

def as_bytes(doc, root):
    doc = dict(doc, generated="2000-01-01T00:00:00Z")
    path = os.path.join(root, "bytes.json")
    write_report(doc, path)
    with open(path, "rb") as f:
        data = f.read()
    os.unlink(path)
    return data

class Tree:
    """A multi-kernel build: the default multiconfig's pkgdata and one
    alternate multiconfig's, the second kernel at another version."""

    def __init__(self, root):
        self.root = root
        self.machine = os.path.join(root, "tmp", "pkgdata", "raspberrypi5")
        self.alt = os.path.join(root, "tmp-raspberrypi-6_6", "pkgdata", "raspberrypi5")
        for d in (self.machine, self.alt):
            os.makedirs(os.path.join(d, "runtime-reverse"))

    def pkg(self, name, recipe, pv, pkgv=None, alt=False):
        base = self.alt if alt else self.machine
        with open(os.path.join(base, "runtime-reverse", name), "w") as f:
            f.write("PN: %s\nPV: %s\nPKGV: %s\nPKGR: r0\n" % (recipe, pv, pkgv or pv))

    def manifest(self, name, entries):
        path = os.path.join(self.root, name + MANIFEST_SUFFIX)
        with open(path, "w") as f:
            json.dump({"package": entries}, f)
        return path

    def kernels(self):
        for alt, pv in ((False, DEFAULT), (True, ALT)):
            short = pv.split("+")[0]
            # kernel.bbclass never puts the version in these names, so both
            # multiconfigs package them; the default's copy wins.
            self.pkg("kernel", "linux-raspberrypi", pv, alt=alt)
            self.pkg("kernel-dev", "linux-raspberrypi", pv, alt=alt)
            self.pkg("kernel-image-image-%s" % short, "linux-raspberrypi", pv, alt=alt)
            self.pkg("kernel-module-foo-%s" % short, "linux-raspberrypi", pv, alt=alt)
            self.pkg("kernel-devsrc-%s" % short, "kernel-devsrc", pv, alt=alt)
        # The alternate multiconfig builds the rest of the image too; none of
        # it reaches the feed.
        self.pkg("base-files", "base-files", "3.0.14", alt=True)
        self.pkg("alt-only-tool", "alt-only-tool", "1.0", alt=True)
        self.pkg("base-files", "base-files", "3.0.14")
        self.pkg("libssl3", "openssl", "3.5.7")

    @property
    def alt_trees(self):
        return [(self.alt, {"linux-raspberrypi", "kernel-devsrc"})]

class AltVersionsTests(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        self.tree = Tree(self.root)
        self.tree.kernels()
        self.scan = self.tree.manifest("feed", [
            entry("linux-raspberrypi", DEFAULT, issue("CVE-2026-1"),
                  issue("CVE-2026-2", "Patched", detail="fixed-version: 6.12.50")),
            # The same id in both kernels: one record each, never merged.
            entry("linux-raspberrypi", ALT, issue("CVE-2026-1"), issue("CVE-2026-3")),
            entry("kernel-devsrc", DEFAULT),
            entry("kernel-devsrc", ALT),
            entry("openssl", "3.5.7", issue("CVE-2026-9")),
            entry("base-files", "3.0.14"),
        ])

    def build(self, scan=None, alt=True, status="All"):
        return build_report([scan or self.scan], [self.tree.machine], machine="m",
                            status=status,
                            alt_trees=self.tree.alt_trees if alt else ())

    def test_the_second_version_is_an_alt_record(self):
        doc, stats = self.build()
        kernel = doc["recipes"]["linux-raspberrypi"]
        self.assertEqual(kernel["version"], DEFAULT)
        self.assertEqual([c["id"] for c in kernel["cves"]], ["CVE-2026-1", "CVE-2026-2"])
        self.assertEqual(kernel["alt_versions"], [{
            "version": ALT, "packaged": True,
            "cves": [issue("CVE-2026-1"), issue("CVE-2026-3")],
        }])
        self.assertEqual(stats.stale_dropped, 0)
        self.assertEqual(doc["counts"]["alt_recipes"], 1)
        self.assertEqual(doc["counts"]["alt_cves"], 2)
        self.assertEqual(doc["counts"]["cves"], 3)
        counts = doc["counts"]
        self.assertEqual(counts["unpatched_cves"] + counts["patched_cves"]
                         + counts["ignored_cves"], counts["cves"] + counts["alt_cves"])

    def test_packages_carry_the_version_they_were_built_from(self):
        doc, _ = self.build()
        packages = doc["packages"]
        self.assertEqual(packages["kernel-module-foo-6.6.78"]["recipe_version"], ALT)
        self.assertEqual(packages["kernel-image-image-6.6.78"]["recipe_version"], ALT)
        self.assertEqual(packages["kernel-module-foo-6.12.87"]["recipe_version"], DEFAULT)
        # A name both multiconfigs package stays the default's.
        self.assertEqual(packages["kernel"]["version"], DEFAULT + "-r0")
        self.assertEqual(packages["kernel"]["recipe_version"], DEFAULT)
        self.assertEqual(packages["libssl3"]["recipe_version"], "3.5.7")
        self.assertEqual(doc["alt_packages"], {
            "kernel-devsrc": {ALT: ["kernel-devsrc-6.6.78"]},
            "linux-raspberrypi": {ALT: ["kernel-image-image-6.6.78",
                                        "kernel-module-foo-6.6.78"]},
        })
        self.assertGreater(doc["counts"]["package_collisions"], 0)

    def test_only_the_named_recipes_are_read_from_the_alternate_tree(self):
        doc, _ = self.build()
        self.assertNotIn("alt-only-tool", doc["packages"])
        self.assertEqual(doc["packages"]["base-files"]["origin"], "raspberrypi5")

    def test_the_binding_files_each_kernel_under_its_own_record(self):
        doc, _ = self.build()
        self.assertEqual(binding_rules.verdict(doc, "kernel-module-foo-6.6.78"),
                         ("checked", {"CVE-2026-1": "affected", "CVE-2026-3": "affected"}))
        self.assertEqual(binding_rules.verdict(doc, "kernel-module-foo-6.12.87"),
                         ("checked", {"CVE-2026-1": "affected", "CVE-2026-2": "patched"}))
        self.assertEqual(binding_rules.verdict(doc, "libssl3"),
                         ("checked", {"CVE-2026-9": "affected"}))

    def test_without_the_alternate_tree_the_second_version_is_stale(self):
        doc, stats = self.build(alt=False)
        self.assertNotIn("alt_versions", doc["recipes"]["linux-raspberrypi"])
        self.assertEqual(stats.stale_dropped, 2)
        self.assertEqual(doc["alt_packages"], {})
        self.assertNotIn("kernel-module-foo-6.6.78", doc["packages"])

    def test_an_alt_version_with_nothing_listed_binds_nothing(self):
        scan = self.tree.manifest("quiet-alt", [
            entry("linux-raspberrypi", DEFAULT, issue("CVE-2026-1")),
            entry("linux-raspberrypi", ALT),
        ])
        doc, _ = self.build(scan)
        self.assertNotIn("alt_versions", doc["recipes"]["linux-raspberrypi"])
        self.assertNotIn("recipe_version", doc["packages"]["kernel-module-foo-6.6.78"])
        self.assertEqual(binding_rules.verdict(doc, "kernel-module-foo-6.6.78"),
                         ("not_checked", "recipe-version-unmatched"))

    def test_the_alt_record_leads_when_the_default_listed_nothing(self):
        # A placeholder entry at the default version with no CVEs would bind
        # the default kernel's packages as scanned and clean.
        scan = self.tree.manifest("quiet-default", [
            entry("linux-raspberrypi", DEFAULT),
            entry("linux-raspberrypi", ALT, issue("CVE-2026-3")),
        ])
        doc, _ = self.build(scan)
        kernel = doc["recipes"]["linux-raspberrypi"]
        self.assertEqual(kernel["version"], ALT)
        self.assertNotIn("alt_versions", kernel)
        self.assertNotIn("recipe_version", doc["packages"]["kernel-module-foo-6.12.87"])
        self.assertEqual(binding_rules.verdict(doc, "kernel-module-foo-6.12.87"),
                         ("not_checked", "recipe-version-unmatched"))
        self.assertEqual(binding_rules.verdict(doc, "kernel-module-foo-6.6.78"),
                         ("checked", {"CVE-2026-3": "affected"}))
        self.assertNotIn("linux-raspberrypi", doc["no_cve_record_recipes"])

    def test_a_rescan_from_the_report_files_them_the_same_way(self):
        anchor = round_trip(self.build()[0], self.root)
        rescan = self.tree.manifest("rescan", [
            entry("linux-raspberrypi", DEFAULT,
                  issue("CVE-2026-1", "Patched", detail="fixed-version: 6.12.90")),
            entry("linux-raspberrypi", ALT, issue("CVE-2026-3"), issue("CVE-2026-4")),
            entry("openssl", "3.5.7"),
        ])
        for status in REPORT_STATUSES:
            with self.subTest(status=status):
                want, want_stats = self.build(rescan, status=status)
                got, got_stats = build_report_from_anchor([rescan], anchor, status=status)
                self.assertEqual(as_bytes(got, self.root), as_bytes(want, self.root))
                self.assertEqual(dict(got_stats), dict(want_stats))
        got, _ = build_report_from_anchor([rescan], anchor)
        self.assertEqual(binding_rules.verdict(got, "kernel-module-foo-6.6.78"),
                         ("checked", {"CVE-2026-3": "affected", "CVE-2026-4": "affected"}))

    def test_a_version_whose_every_name_the_default_took_is_still_its_own(self):
        # Each of its packages lost its name to the default's, so none carries
        # the version; its CVEs still must not join the default's record.
        self.tree.pkg("libfoo", "foo", "2.0")
        self.tree.pkg("libfoo", "foo", "2.1", alt=True)
        scan = self.tree.manifest("foo", [
            entry("foo", "2.0", issue("CVE-2026-7")),
            entry("foo", "2.1", issue("CVE-2026-8")),
        ])
        doc, _ = build_report([scan], [self.tree.machine], status="All",
                              alt_trees=[(self.tree.alt, {"foo"})])
        foo = doc["recipes"]["foo"]
        self.assertEqual([c["id"] for c in foo["cves"]], ["CVE-2026-7"])
        self.assertEqual(foo["alt_versions"][0]["version"], "2.1")
        self.assertEqual(doc["alt_packages"], {"foo": {"2.1": []}})
        self.assertEqual(binding_rules.verdict(doc, "libfoo"),
                         ("checked", {"CVE-2026-7": "affected"}))

    def test_an_earlier_report_keeps_an_alt_record_that_owns_no_package(self):
        self.tree.pkg("libfoo", "foo", "2.0")
        self.tree.pkg("libfoo", "foo", "2.1", alt=True)
        scan = self.tree.manifest("foo", [
            entry("foo", "2.0", issue("CVE-2026-7")),
            entry("foo", "2.1", issue("CVE-2026-8")),
        ])
        doc, _ = build_report([scan], [self.tree.machine], status="All",
                              alt_trees=[(self.tree.alt, {"foo"})])
        anchor = round_trip(doc, self.root)
        del anchor["alt_packages"]
        again, _ = build_report_from_anchor([scan], anchor)
        self.assertEqual(again["alt_packages"]["foo"], {"2.1": []})
        self.assertEqual(binding_rules.verdict(again, "libfoo"),
                         ("checked", {"CVE-2026-7": "affected"}))

    def test_a_rescan_leaves_the_report_it_was_given_alone(self):
        anchor = round_trip(self.build()[0], self.root)
        before = json.dumps(anchor, sort_keys=True)
        quiet = self.tree.manifest("quiet", [entry("openssl", "3.5.7")])
        doc, _ = build_report_from_anchor([quiet], anchor)
        self.assertEqual(json.dumps(anchor, sort_keys=True), before)
        self.assertNotIn("recipe_version", doc["packages"]["kernel-module-foo-6.6.78"])

    def test_a_report_with_an_earlier_alt_record_keeps_the_split(self):
        # A report written before alt_packages existed, which already filed the
        # second kernel under alt_versions and stamped its packages.
        anchor = round_trip(self.build()[0], self.root)
        del anchor["alt_packages"]
        rescan = self.tree.manifest("image-only", [
            entry("linux-raspberrypi", DEFAULT, issue("CVE-2026-1")),
        ])
        doc, _ = build_report_from_anchor([rescan], anchor)
        self.assertEqual(doc["alt_packages"]["linux-raspberrypi"],
                         {ALT: ["kernel-image-image-6.6.78", "kernel-module-foo-6.6.78"]})
        self.assertEqual(binding_rules.verdict(doc, "kernel-module-foo-6.6.78"),
                         ("not_checked", "recipe-version-unmatched"))
        self.assertEqual(binding_rules.verdict(doc, "kernel-module-foo-6.12.87"),
                         ("checked", {"CVE-2026-1": "affected"}))

    def test_a_malformed_alt_packages_is_refused(self):
        anchor = round_trip(self.build()[0], self.root)
        for value in ([], {"linux-raspberrypi": []},
                      {"linux-raspberrypi": {ALT: "kernel"}},
                      {"linux-raspberrypi": {"": []}},
                      {"linux-raspberrypi": {ALT: ["no-such-package"]}},
                      {"openssl": {ALT: ["kernel-module-foo-6.6.78"]}}):
            with self.subTest(value=value):
                bad = json.loads(json.dumps(anchor))
                bad["alt_packages"] = value
                with self.assertRaises(ValueError) as ctx:
                    build_report_from_anchor([self.scan], bad)
                self.assertIn("alt_packages", str(ctx.exception))

class NoCveRecordTests(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        self.tree = Tree(self.root)
        for recipe in ("avocadoctl", "glibc-locale", "zlib", "attr", "acl",
                       "busybox", "dbus", "cmocka", "twice"):
            self.tree.pkg("pkg-" + recipe, recipe, "1.0")

    def build(self, entries, status="All"):
        scan = self.tree.manifest("scan", entries)
        doc, stats = build_report([scan], [self.tree.machine], status=status)
        return doc, stats, scan

    def entries(self):
        return [
            # A CPE no CVE record names, and none at all: both export an
            # empty issue list.
            entry("avocadoctl", "1.0"),
            entry("glibc-locale", "1.0"),
            entry("zlib", "1.0", issue("CVE-2026-1", "Patched",
                                       detail="fixed-version: 0.9")),
            # Scanned only at a version this build does not have.
            entry("attr", "0.9", issue("CVE-2026-2")),
            # Only a status this report does not know.
            entry("busybox", "1.0", issue("CVE-2026-3", "Bogus")),
            # A malformed issue list, and none at all.
            {"name": "dbus", "version": "1.0", "issue": "none"},
            {"name": "cmocka", "version": "1.0"},
            # Two copies, one with a match.
            entry("twice", "1.0"),
            entry("twice", "1.0", issue("CVE-2026-4")),
            # "acl" has no entry at all.
        ]

    def test_the_list_is_what_the_scanner_could_not_match(self):
        doc, stats, _ = self.build(self.entries())
        self.assertEqual(doc["no_cve_record_recipes"], ["avocadoctl", "glibc-locale"])
        self.assertEqual(doc["counts"]["no_cve_record_recipes"], 2)
        self.assertEqual(binding_rules.verdict(doc, "pkg-avocadoctl"),
                         ("not_checked", "no-cve-record"))

    def test_what_was_not_usably_scanned_is_unscanned_never_clean(self):
        doc, stats, _ = self.build(self.entries())
        self.assertEqual(doc["unscanned_recipes"],
                         ["acl", "attr", "busybox", "cmocka", "dbus"])
        self.assertEqual(stats.stale_dropped, 1)
        self.assertEqual(stats.entries_unreadable, 2)
        for recipe in ("acl", "attr", "busybox", "cmocka", "dbus"):
            self.assertEqual(binding_rules.verdict(doc, "pkg-" + recipe),
                             ("not_checked", "recipe-unscanned"))

    def test_every_shipped_recipe_is_accounted_for_at_all(self):
        doc, _, _ = self.build(self.entries())
        lists = [set(doc["recipes"]), set(doc["no_cve_record_recipes"]),
                 set(doc["unscanned_recipes"])]
        shipped = {p["recipe"] for p in doc["packages"].values()}
        for recipe in shipped:
            self.assertEqual(sum(recipe in each for each in lists), 1, recipe)
        for name in doc["packages"]:
            self.assertNotEqual(binding_rules.coverage(doc, name), ("scanned", []), name)

    def test_a_single_status_report_keeps_matched_recipes_out_of_the_lists(self):
        # zlib matched a CVE that this status leaves out: clean at Unpatched,
        # as before, rather than unscanned.
        doc, _, _ = self.build(self.entries(), status="Unpatched")
        self.assertNotIn("zlib", doc["recipes"])
        self.assertNotIn("zlib", doc["unscanned_recipes"])
        self.assertNotIn("zlib", doc["no_cve_record_recipes"])

    def test_the_list_is_scoped_to_recipes_that_shipped(self):
        doc, _, _ = self.build(self.entries() + [entry("gcc-cross", "1.0")])
        self.assertNotIn("gcc-cross", doc["no_cve_record_recipes"])

    def test_a_rescan_from_the_report_lists_the_same(self):
        doc, _, _ = self.build(self.entries())
        anchor = round_trip(doc, self.root)
        rescan = self.tree.manifest("rescan", self.entries()[2:] + [
            entry("avocadoctl", "1.0", issue("CVE-2026-5")),
            entry("acl", "1.0"),
        ])
        want, _ = build_report([rescan], [self.tree.machine], status="All")
        got, _ = build_report_from_anchor([rescan], anchor)
        self.assertEqual(as_bytes(got, self.root), as_bytes(want, self.root))
        self.assertEqual(got["no_cve_record_recipes"], ["acl"])
        self.assertIn("avocadoctl", got["recipes"])

class UpstreamWontfixTests(unittest.TestCase):
    """create-spdx writes a CVE_STATUS keyword as the VEX statement's status
    notes and sbom-cve-check exports those as "detail"; the report keeps it."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        self.tree = Tree(self.root)
        self.tree.pkg("shadow", "shadow", "4.19.4")
        self.scan = self.tree.manifest("scan", [entry(
            "shadow", "4.19.4",
            issue("CVE-2013-4235", "Ignored", detail="upstream-wontfix",
                  description="Severity is low and marked as closed and won't fix."),
            issue("CVE-2026-6", "Ignored", detail="cpe-incorrect"),
        )])

    def test_the_detail_survives_both_paths_and_no_summary(self):
        for summary in (True, False):
            with self.subTest(summary=summary):
                doc, _ = build_report([self.scan], [self.tree.machine],
                                      status="All", summary=summary)
                anchor = round_trip(doc, self.root)
                again, _ = build_report_from_anchor([self.scan], anchor, summary=summary)
                for each in (doc, again):
                    cves = {c["id"]: c for c in each["recipes"]["shadow"]["cves"]}
                    self.assertEqual(cves["CVE-2013-4235"]["detail"], "upstream-wontfix")
                    self.assertEqual(binding_rules.verdict(each, "shadow"),
                                     ("checked", {"CVE-2013-4235": "affected"}))

class AltTreeHelpersTests(unittest.TestCase):

    def test_alt_path(self):
        self.assertEqual(
            feedsbom.alt_path("/b", "/b/tmp", "/b/tmp/pkgdata/raspberrypi5", "rpi-6_6"),
            "/b/tmp-rpi-6_6/pkgdata/raspberrypi5")
        self.assertEqual(
            feedsbom.alt_path("/b", "/b/tmp/", "/b/tmp/deploy/rpm", "mc"),
            "/b/tmp-mc/deploy/rpm")
        for path in ("/b/tmpx/pkgdata", "/elsewhere/pkgdata", "/b/tmp"):
            with self.subTest(path=path):
                with self.assertRaises(feedsbom.FeedSbomError):
                    feedsbom.alt_path("/b", "/b/tmp", path, "mc")

    def test_an_alternate_tree_must_hold_every_declared_recipe(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root)
        tree = Tree(root)
        recipes = {"linux-raspberrypi", "kernel-devsrc"}
        # Empty, then only a dependency the feed does not take from it.
        self.assertIn("no package of kernel-devsrc, linux-raspberrypi",
                      report.alt_tree_problem(tree.alt, recipes))
        self.assertEqual(report.alt_tree_problem(tree.alt, None),
                         "%s holds no readable package data" % tree.alt)
        tree.pkg("base-files", "base-files", "3.0.14", alt=True)
        self.assertIn("no package of kernel-devsrc, linux-raspberrypi",
                      report.alt_tree_problem(tree.alt, recipes))
        self.assertIsNone(report.alt_tree_problem(tree.alt, None))
        tree.pkg("kernel-image-6.6.78", "linux-raspberrypi", ALT, alt=True)
        self.assertIn("no package of kernel-devsrc",
                      report.alt_tree_problem(tree.alt, recipes))
        tree.pkg("kernel-devsrc-6.6.78", "kernel-devsrc", ALT, alt=True)
        self.assertIsNone(report.alt_tree_problem(tree.alt, recipes))
        self.assertIn("no runtime-reverse",
                      report.alt_tree_problem(os.path.join(root, "nowhere"), recipes))

    def test_alt_recipes_by_mc(self):
        pairs, _ = feedsbom.parse_alt_recipes(
            "b:linux b:kernel-devsrc a:linux-l4t b:linux")
        self.assertEqual(list(feedsbom.alt_recipes_by_mc(pairs).items()),
                         [("b", {"linux", "kernel-devsrc"}), ("a", {"linux-l4t"})])

class CliTests(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        self.tree = Tree(self.root)
        self.tree.kernels()
        self.scan = self.tree.manifest("feed", [
            entry("linux-raspberrypi", DEFAULT, issue("CVE-2026-1")),
            entry("linux-raspberrypi", ALT, issue("CVE-2026-3")),
        ])

    def run_main(self, *argv):
        err = io.StringIO()
        with mock.patch.object(sys, "argv", ["report"] + list(argv)), \
                contextlib.redirect_stderr(err):
            try:
                rc = report.main()
            except SystemExit as e:
                rc = e.code
        return rc, err.getvalue()

    def test_the_cli_reads_an_alternate_tree(self):
        out = os.path.join(self.root, "out.json")
        rc, err = self.run_main(
            "--manifest", self.scan, "--pkgdata-dir", self.tree.machine,
            "--alt-pkgdata-dir", self.tree.alt, "--alt-recipe", "linux-raspberrypi",
            "--alt-recipe", "kernel-devsrc", "--status", "All", "-o", out)
        self.assertEqual(rc, 0, err)
        self.assertIn("alt_recipes: 1", err)
        with open(out) as f:
            doc = json.load(f)
        want, _ = build_report([self.scan], [self.tree.machine], status="All",
                               alt_trees=self.tree.alt_trees)
        doc["generated"] = want["generated"]
        self.assertEqual(doc, json.loads(json.dumps(want)))

    def test_the_cli_refuses_an_alternate_tree_without_package_data(self):
        empty = os.path.join(self.root, "tmp-empty", "pkgdata", "raspberrypi5")
        os.makedirs(empty)
        out = os.path.join(self.root, "out.json")
        rc, err = self.run_main(
            "--manifest", self.scan, "--pkgdata-dir", self.tree.machine,
            "--alt-pkgdata-dir", empty, "--status", "All", "-o", out)
        self.assertEqual(rc, 2)
        self.assertIn("runtime-reverse", err)
        self.assertFalse(os.path.exists(out))

    def test_the_cli_refuses_an_alternate_tree_without_a_declared_recipe(self):
        out = os.path.join(self.root, "out.json")
        rc, err = self.run_main(
            "--manifest", self.scan, "--pkgdata-dir", self.tree.machine,
            "--alt-pkgdata-dir", self.tree.alt, "--alt-recipe", "linux-raspberrypi",
            "--alt-recipe", "linux-other", "--status", "All", "-o", out)
        self.assertEqual(rc, 2)
        self.assertIn("no package of linux-other", err)
        self.assertFalse(os.path.exists(out))

    def test_from_report_refuses_an_alternate_tree(self):
        out = os.path.join(self.root, "out.json")
        rc, _ = self.run_main("--from-report", out, "--manifest", self.scan,
                              "--alt-pkgdata-dir", self.tree.alt, "-o", out)
        self.assertEqual(rc, 2)

if __name__ == "__main__":
    unittest.main()
