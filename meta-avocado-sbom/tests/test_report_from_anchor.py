#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""Prove a report rebuilt from a previous report equals the one the build
would have written for the same scan: from a version 2 report, and from a
version 1 report of one tree, which is upgraded with its packages_digest
unchanged. A version 1 report with alternate multiconfig content is refused.

  python3 -m unittest discover -s meta-avocado-sbom/tests -p 'test_*.py'
"""

import contextlib
import io
import json
import os
import random
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

import report_trees as rt  # noqa: E402
from avocado_sbom import report  # noqa: E402
from avocado_sbom.report import (  # noqa: E402
    REPORT_STATUSES,
    AnchorUnsupported,
    build_report,
    build_report_from_anchor,
)
from report_trees import as_bytes, entry, issue, normalized, round_trip  # noqa: E402


def in_build(manifests, tree, machine, status, summary, distro="2026.1", **kwargs):
    """What do_cve_report writes."""
    doc, stats = build_report(manifests, tree.dirs, machine=machine, status=status,
                              summary=summary, alt_trees=tree.alt_trees, **kwargs)
    if distro:
        doc["distro_version"] = distro
    return doc, stats


class EquivalenceTests(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        self.tree = rt.Tree(self.root)

    def populate(self):
        self.build_scan = rt.one_tree(self.tree)
        self.rescan = rt.one_tree_rescan(self.tree)

    def assert_equivalent(self, status, summary, anchor_status="All", **kwargs):
        self.populate()
        anchor_doc, _ = in_build([self.build_scan], self.tree, rt.MACHINE,
                                 anchor_status, summary, **kwargs)
        anchor = round_trip(anchor_doc, self.root)

        want, want_stats = in_build(self.rescan, self.tree, rt.MACHINE, status, summary,
                                    **kwargs)
        got, got_stats = build_report_from_anchor(self.rescan, anchor, status=status)

        self.assertEqual(as_bytes(got, self.root), as_bytes(want, self.root))
        self.assertEqual(dict(got_stats), dict(want_stats))
        return got

    def test_every_status_and_summary_gives_the_same_bytes(self):
        for status in REPORT_STATUSES:
            for summary in (True, False):
                for compiled in (None, {"linux-raspberrypi"}):
                    with self.subTest(status=status, summary=summary, compiled=compiled):
                        self.setUp()
                        self.assert_equivalent(status, summary, compiled_sources=compiled)

    def test_the_fixture_exercises_every_path(self):
        doc = self.assert_equivalent("All", True)
        counts = doc["counts"]
        for key in ("stale_dropped", "unscanned_builds",
                    "cve_files_unreadable", "entries_unreadable", "pkgdata_unreadable",
                    "package_collisions", "unknown_status_cves", "patched_cves",
                    "ignored_cves"):
            self.assertGreater(counts[key], 0, key)
        builds = doc["builds"]
        self.assertIs(builds["packagegroup-x"]["packaged"], True)
        self.assertIs(builds["openssl-vendor"]["packaged"], True)
        self.assertIs(builds["busybox-native"]["packaged"], False)
        self.assertEqual(builds["glibc"]["coverage"], "scanned")
        self.assertEqual(builds["openssl"]["coverage"], "unscanned")
        self.assertEqual(builds["dbus"]["version"], "1.16.2")
        self.assertEqual(doc["machine"], rt.MACHINE)
        self.assertEqual(doc["distro_version"], "2026.1")

    def test_status_and_summary_default_to_the_anchors(self):
        self.populate()
        anchor = round_trip(in_build([self.build_scan], self.tree, rt.MACHINE,
                                     "Patched", False)[0], self.root)
        doc, _ = build_report_from_anchor(self.rescan, anchor)
        self.assertEqual((doc["status"], doc["summary"]), ("Patched", False))
        glibc = doc["builds"]["glibc"]["cves"]
        self.assertTrue(glibc)
        self.assertFalse([c for c in glibc if "summary" in c or "description" in c])

    def test_no_machine_or_distro_version_stays_absent(self):
        self.populate()
        anchor = round_trip(in_build([self.build_scan], self.tree, None, "All", True,
                                     distro=None)[0], self.root)
        want, _ = in_build(self.rescan, self.tree, None, "All", True, distro=None)
        got, _ = build_report_from_anchor(self.rescan, anchor)
        self.assertNotIn("machine", got)
        self.assertNotIn("distro_version", got)
        self.assertEqual(as_bytes(got, self.root), as_bytes(want, self.root))


class AlternateEquivalenceTests(unittest.TestCase):
    """A rebuild keeps each alternate build apart, the builds the document
    left out included."""

    def test_alternates_and_a_left_out_build(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root)
        tree = rt.Tree(root)
        rt.rpi_kernels(tree)
        not_covered = {"%s:kernel-devsrc" % rt.RPI_MC: "unresolved reference: 1 identifier(s)"}
        scan = tree.manifest("feed", {"package": [
            entry("linux-raspberrypi", rt.DEFAULT_KERNEL, issue("CVE-2026-1")),
            entry("%s:linux-raspberrypi" % rt.RPI_MC, rt.ALT_KERNEL, issue("CVE-2026-3")),
            entry("kernel-devsrc", rt.DEFAULT_KERNEL),
            entry("openssl", "3.5.7", issue("CVE-2026-9")),
        ]})
        rescan = tree.manifest("rescan", {"package": [
            entry("linux-raspberrypi", rt.DEFAULT_KERNEL, issue("CVE-2026-1", "Patched")),
            entry("%s:linux-raspberrypi" % rt.RPI_MC, rt.ALT_KERNEL, issue("CVE-2026-3"),
                  issue("CVE-2026-4")),
        ]})
        anchor = round_trip(in_build([scan], tree, rt.MACHINE, "All", True,
                                     not_covered=not_covered)[0], root)
        for status in REPORT_STATUSES:
            with self.subTest(status=status):
                want, want_stats = in_build([rescan], tree, rt.MACHINE, status, True,
                                            not_covered=not_covered)
                got, got_stats = build_report_from_anchor([rescan], anchor, status=status)
                self.assertEqual(as_bytes(got, root), as_bytes(want, root))
                self.assertEqual(dict(got_stats), dict(want_stats))
        got, _ = build_report_from_anchor([rescan], anchor)
        devsrc = got["builds"]["%s:kernel-devsrc" % rt.RPI_MC]
        self.assertEqual((devsrc["coverage"], devsrc["not_covered"]),
                         ("unscanned", not_covered["%s:kernel-devsrc" % rt.RPI_MC]))
        self.assertEqual([c["id"] for c in got["builds"]["%s:linux-raspberrypi" % rt.RPI_MC]
                          ["cves"]], ["CVE-2026-3", "CVE-2026-4"])
        self.assertEqual(got["packages_digest"], anchor["packages_digest"])


class RandomizedEquivalenceTests(unittest.TestCase):
    """Generated builds and scans, seeded so a failure reproduces."""

    VERSIONS = ("1.0", "2.43+git", "6.12.87+git", "3.5.7", "0.9.1")
    STATUSES = ("Unpatched", "Patched", "Ignored", "Unpatched", "Bogus", None)

    def generate(self, rng, root):
        tree = rt.Tree(root)
        recipes = ["r%d" % i for i in range(rng.randint(1, 12))]
        pv = {r: rng.choice(self.VERSIONS) for r in recipes}
        for r in recipes:
            for i in range(rng.randint(1, 3)):
                pkgv = pv[r] if rng.random() < 0.6 else pv[r] + "+git%d+cafe" % i
                roll = rng.random()
                if roll < 0.05:
                    text = "PV: %s\n" % pv[r]
                elif roll < 0.12:
                    text = "PN: %s\nPV: %s\nPKGV:%s-%d: 9.%d\nPKGR:%s-%d: r1\n" % (
                        r, pv[r], r, i, i, r, i)
                elif roll < 0.16:
                    text = "PN: %s\n" % r
                else:
                    text = "PN: %s\nPV: %s\nPKGV: %s\nPKGR: r%d\n" % (r, pv[r], pkgv, i)
                tree.write("%s-%d" % (r, i), text)
                if rng.random() < 0.15:
                    other = rng.choice(recipes) + "-sdk"
                    tree.write("%s-%d" % (r, i),
                               "PN: %s\nPV: 1.0\nPKGV: 1.0\nPKGR: r0\n" % other, sdk=True)

        # Alternate multiconfigs: some recipes again at another version, some
        # at the same version and release (one package build), one only they
        # build, names the default packages too, and some left out.
        alt_pv = {}
        not_covered = {}
        for mc in ("mc-a", "mc-b")[:rng.randint(0, 2)]:
            versions = alt_pv[mc] = {}
            for r in rng.sample(recipes, rng.randint(1, len(recipes))):
                versions[r] = rng.choice(self.VERSIONS + ("9.9-alt", "7.7-alt"))
            versions["alt-only"] = "4.2"
            tree.alt(mc, set(versions) if rng.random() < 0.7 else None)
            for r, v in versions.items():
                for i in range(rng.randint(1, 3)):
                    name = "%s-%d" % (r, i) if rng.random() < 0.5 else "%s-%s-%d" % (r, v, i)
                    tree.pkg(name, r, v, pkgr="r%d" % i, mc=mc)
                if rng.random() < 0.2:
                    not_covered["%s:%s" % (mc, r)] = "VEX overlap: x"

        def scan(name):
            names = recipes + ["%s-sdk" % r for r in recipes] + ["stray"]
            names += ["%s:%s" % (mc, r) for mc, versions in alt_pv.items() for r in versions]
            entries = []
            for n in rng.sample(names, rng.randint(0, len(names))):
                mc, _sep, r = n.rpartition(":")
                v = alt_pv[mc][r] if mc else pv.get(n, "1.0")
                roll = rng.random()
                if roll < 0.1:
                    v = "1_" + v
                elif roll < 0.2:
                    v = "8.8"
                if rng.random() < 0.03:
                    entries.append({"name": n, "version": 3})
                    continue
                issues = []
                for _ in range(rng.randint(0, 4)):
                    item = {"id": "CVE-2026-%d" % rng.randint(1, 30),
                            "summary": "s", "description": "d", "scorev3": "5.0"}
                    status = rng.choice(self.STATUSES)
                    if status is not None:
                        item["status"] = status
                    issues.append(item)
                entries.append({"name": n, "version": v, "issue": issues})
            return tree.manifest(name, {"package": entries})

        manifests = [scan("m%d" % i) for i in range(rng.randint(1, 2))]
        if rng.random() < 0.1:
            manifests.append(tree.manifest("bad", "[]"))
        return tree, not_covered, scan("build"), manifests

    def assert_accounted(self, doc, seed):
        """Every package build names a packaged build, at most once per
        normalized version, and at All every packaged build has a coverage
        state that matches what it carries."""
        for name, entries in doc["packages"].items():
            versions = [report.normalize_version(e["version"]) for e in entries]
            self.assertEqual(len(versions), len(set(versions)), "seed %d: %s" % (seed, name))
            for e in entries:
                self.assertIs(doc["builds"][e["build"]]["packaged"], True, "seed %d" % seed)
        for bid, build in doc["builds"].items():
            self.assertEqual("cves" in build, build["coverage"] == "scanned",
                             "seed %d: %s" % (seed, bid))
            if "not_covered" in build:
                self.assertEqual(build["coverage"], "unscanned", "seed %d" % seed)

    def test_generated_builds(self):
        with_alt = shared = left_out = 0
        for seed in range(300):
            rng = random.Random(seed)
            root = tempfile.mkdtemp()
            try:
                tree, not_covered, build_scan, manifests = self.generate(rng, root)
                status = rng.choice(REPORT_STATUSES)
                summary = rng.random() < 0.5
                compiled = rng.choice((None, set(), {"r0", "r1"}))
                anchor_doc, stats = in_build([build_scan], tree, "m",
                                             rng.choice(REPORT_STATUSES), summary,
                                             not_covered=not_covered,
                                             compiled_sources=compiled)
                if not stats.packages:
                    continue
                anchor = round_trip(anchor_doc, root)
                want, want_stats = in_build(manifests, tree, "m", status, summary,
                                            not_covered=not_covered,
                                            compiled_sources=compiled)
                got, got_stats = build_report_from_anchor(manifests, anchor, status=status)
                self.assertEqual(as_bytes(got, root), as_bytes(want, root), "seed %d" % seed)
                self.assertEqual(dict(got_stats), dict(want_stats), "seed %d" % seed)
                with_alt += bool(want["counts"]["alternate_builds"])
                shared += bool(want["counts"]["shared_package_builds"])
                left_out += bool(want["counts"]["not_covered_builds"])
                self.assert_accounted(want, seed)
            finally:
                shutil.rmtree(root)
        self.assertGreater(with_alt, 100)
        self.assertGreater(shared, 30)
        self.assertGreater(left_out, 30)


class VersionOneTests(unittest.TestCase):
    """The version 1 reports tests/fixtures/report-v1 holds, written by the
    previous generator for report_trees' one_tree and rpi_kernels builds."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        self.tree = rt.Tree(self.root)

    def test_one_tree_is_upgraded_to_what_the_build_writes_now(self):
        anchor = rt.load_fixture("one-tree.json")
        self.assertEqual(anchor["version"], "1")
        rt.one_tree(self.tree)
        rescan = rt.one_tree_rescan(self.tree)
        for status in REPORT_STATUSES:
            with self.subTest(status=status):
                got, got_stats = build_report_from_anchor(rescan, anchor, status=status)
                want, want_stats = in_build(rescan, self.tree, rt.MACHINE, status, True,
                                            compiled_sources={"linux-raspberrypi"})
                self.assertEqual(got["version"], "2")
                self.assertEqual(got["packages_digest"], anchor["packages_digest"])
                self.assertEqual(as_bytes(got, self.root), as_bytes(want, self.root))
                self.assertEqual(dict(got_stats), dict(want_stats))

    def test_the_digest_is_the_version_one_digest_on_one_tree(self):
        anchor = rt.load_fixture("one-tree.json")
        scan = rt.one_tree(self.tree)
        doc, _ = in_build([scan], self.tree, rt.MACHINE, "All", True)
        self.assertEqual(doc["packages_digest"], anchor["packages_digest"])
        self.assertEqual(
            {n: [e["version"] for e in v] for n, v in doc["packages"].items()},
            {n: [p["version"] for p in [p]] for n, p in anchor["packages"].items()})

    def test_without_its_list_the_upgrade_trusts_kernels_only(self):
        anchor = rt.load_fixture("one-tree.json")
        del anchor["compiled_source_recipes"]
        rt.one_tree(self.tree)
        rescan = rt.one_tree_rescan(self.tree)
        got, _ = build_report_from_anchor(rescan, anchor)
        want, _ = in_build(rescan, self.tree, rt.MACHINE, "All", True)
        self.assertNotIn("compiled_sources", got["builds"]["glibc"])
        self.assertEqual(as_bytes(got, self.root), as_bytes(want, self.root))

    def test_alternate_content_is_refused_by_name(self):
        anchor = rt.load_fixture("alternates.json")
        rt.rpi_kernels(self.tree)
        scan = self.tree.manifest("s", {"package": [entry("openssl", "3.5.7")]})
        for drop in (None, "alt_packages", "alt_versions"):
            with self.subTest(drop=drop):
                doc = json.loads(json.dumps(anchor))
                if drop == "alt_packages":
                    doc["alt_packages"] = {}
                elif drop == "alt_versions":
                    del doc["recipes"]["linux-raspberrypi"]["alt_versions"]
                with self.assertRaises(AnchorUnsupported) as ctx:
                    build_report_from_anchor([scan], doc)
                self.assertIn("linux-raspberrypi", str(ctx.exception))
                self.assertIn("alternate multiconfig", str(ctx.exception))
        # Both gone: what is left reads as one tree.
        doc = json.loads(json.dumps(anchor))
        doc["alt_packages"] = {}
        del doc["recipes"]["linux-raspberrypi"]["alt_versions"]
        got, _ = build_report_from_anchor([scan], doc)
        self.assertEqual(got["packages_digest"], anchor["packages_digest"])

    def test_alternate_content_is_a_value_error_too(self):
        # The rescan worker fails a build on ValueError; it tells this one apart.
        self.assertTrue(issubclass(AnchorUnsupported, ValueError))

    def test_a_report_without_recipe_versions_is_refused(self):
        anchor = rt.load_fixture("one-tree.json")
        del anchor["recipe_versions"]
        with self.assertRaises(ValueError) as ctx:
            build_report_from_anchor([rt.one_tree(self.tree)], anchor)
        self.assertNotIsInstance(ctx.exception, AnchorUnsupported)
        self.assertIn("scanned before the report carried them", str(ctx.exception))

    def test_an_empty_recipe_versions_is_accepted(self):
        anchor = rt.load_fixture("one-tree.json")
        anchor["recipe_versions"] = {}
        doc, _ = build_report_from_anchor([rt.one_tree(self.tree)], anchor)
        self.assertIs(doc["builds"]["zlib"]["packaged"], True)
        self.assertEqual(doc["builds"]["zlib"]["version_keys"], [])

    def test_malformed_version_one_parts_are_refused(self):
        base = rt.load_fixture("one-tree.json")
        cases = (
            ("packages", {}, "packages"),
            ("packages", {"libz1": {"recipe": "zlib"}}, "packages"),
            ("recipe_versions", {"zlib": "1.3.1"}, "recipe_versions"),
            ("recipe_versions", {"zlib": []}, "recipe_versions"),
            ("alt_packages", [], "alt_packages"),
            ("recipes", [], "recipes"),
            ("compiled_source_recipes", "zlib", "compiled_source_recipes"),
            ("counts", None, "counts"),
            ("machine", "", "machine"),
        )
        for key, value, words in cases:
            with self.subTest(key=key, value=value):
                anchor = json.loads(json.dumps(base))
                anchor[key] = value
                with self.assertRaises(ValueError) as ctx:
                    build_report_from_anchor([rt.one_tree(self.tree)], anchor)
                self.assertIn(words, str(ctx.exception))
                self.setUp()
        anchor = json.loads(json.dumps(base))
        anchor["packages"]["libz1"]["version"] = "1.3.2-r0"
        with self.assertRaises(ValueError) as ctx:
            build_report_from_anchor([rt.one_tree(self.tree)], anchor)
        self.assertIn("packages_digest", str(ctx.exception))


class AnchorRefusalTests(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        self.tree = rt.Tree(self.root)
        rt.rpi_kernels(self.tree)
        self.manifest = self.tree.manifest("m", {"package": [
            entry("linux-raspberrypi", rt.DEFAULT_KERNEL, issue("CVE-2026-1")),
            entry("libssl3-native", "3.5.7"),
        ]})
        self.anchor = round_trip(build_report(
            [self.manifest], self.tree.dirs, machine="m", status="All",
            alt_trees=self.tree.alt_trees, compiled_sources=set(),
            not_covered={"%s:kernel-devsrc" % rt.RPI_MC: "why"})[0], self.root)

    def refused(self, anchor, words):
        with self.assertRaises(ValueError) as ctx:
            build_report_from_anchor([self.manifest], anchor)
        self.assertNotIsInstance(ctx.exception, AnchorUnsupported)
        self.assertIn(words, str(ctx.exception))

    def test_another_report_version_is_refused(self):
        for version in ("3", 2, None):
            with self.subTest(version=version):
                anchor = json.loads(json.dumps(self.anchor))
                anchor["version"] = version
                self.refused(anchor, "report version")

    def test_edited_packages_are_refused(self):
        for edit in ("version", "build", "drop"):
            with self.subTest(edit=edit):
                anchor = json.loads(json.dumps(self.anchor))
                kernel = anchor["packages"]["kernel"]
                if edit == "version":
                    kernel[0]["version"] = "6.12.88-r0"
                elif edit == "build":
                    kernel[1]["build"] = "linux-raspberrypi"
                    kernel[1]["version"] = "6.6.78-git-r1"
                else:
                    del kernel[1]
                self.refused(anchor, "packages_digest")

    def test_malformed_builds_are_refused(self):
        alt = "%s:linux-raspberrypi" % rt.RPI_MC
        cases = (
            (None, "builds"),
            ({}, "builds"),
            ({alt: dict(self.anchor["builds"][alt], mc="")}, "builds"),
            ({alt: dict(self.anchor["builds"][alt], coverage="clean")}, "builds"),
            ({alt: dict(self.anchor["builds"][alt], packaged="yes")}, "builds"),
            ({alt: dict(self.anchor["builds"][alt], version_keys="6.6")}, "builds"),
            ({alt: dict(self.anchor["builds"][alt], compiled_sources=1)}, "builds"),
            ({alt: dict(self.anchor["builds"][alt], not_covered="")}, "builds"),
        )
        for value, words in cases:
            with self.subTest(value=value):
                anchor = json.loads(json.dumps(self.anchor))
                if isinstance(value, dict) and value:
                    anchor["builds"].update(value)
                else:
                    anchor["builds"] = value
                self.refused(anchor, words)

    def test_a_packaged_build_without_version_keys_is_refused(self):
        alt = "%s:linux-raspberrypi" % rt.RPI_MC
        del self.anchor["builds"][alt]["version_keys"]
        self.refused(self.anchor, "builds[%r] is packaged and has no version_keys" % alt)

    def test_version_keys_may_be_empty_or_absent_where_pkgdata_gives_none(self):
        self.assertIs(self.anchor["builds"]["libssl3-native"]["packaged"], False)
        self.assertNotIn("version_keys", self.anchor["builds"]["libssl3-native"])
        self.anchor["builds"]["openssl"]["version_keys"] = []
        doc, _ = build_report_from_anchor([self.manifest], self.anchor)
        self.assertEqual(doc["builds"]["openssl"]["version_keys"], [])

    def test_a_flag_on_some_builds_only_is_refused(self):
        del self.anchor["builds"]["openssl"]["compiled_sources"]
        self.refused(self.anchor, "compiled_sources is on some builds")

    def test_malformed_packages_are_refused(self):
        cases = (
            {},
            {"kernel": []},
            {"kernel": {"version": "1", "build": "linux-raspberrypi"}},
            {"kernel": [{"version": "1", "build": "nowhere"}]},
            {"kernel": [{"version": 1, "build": "linux-raspberrypi"}]},
            # A build id that isn't a string must be a validation error, not a TypeError.
            {"kernel": [{"version": "1", "build": []}]},
            {"kernel": [{"version": "1", "build": {}}]},
            # A build only an entry made, no package data behind it.
            {"kernel": [{"version": "1", "build": "libssl3-native"}]},
            {"kernel": [{"version": "1+a", "build": "linux-raspberrypi"},
                        {"version": "1-a", "build": "linux-raspberrypi"}]},
        )
        for value in cases:
            with self.subTest(value=value):
                anchor = json.loads(json.dumps(self.anchor))
                anchor["packages"] = value if not value or "kernel" not in value else dict(
                    anchor["packages"], **value)
                self.refused(anchor, "packages")

    def test_malformed_parts_are_refused(self):
        cases = (
            ("counts", None, "counts"),
            ("summary", "yes", "summary"),
            ("machine", ["m"], "machine"),
            ("machine", "", "machine"),
            ("distro_version", {"v": 1}, "distro_version"),
        )
        for key, value, words in cases:
            with self.subTest(key=key, value=value):
                anchor = json.loads(json.dumps(self.anchor))
                anchor[key] = value
                self.refused(anchor, words)
        for key in ("pkgdata_unreadable", "package_collisions", "shared_package_builds"):
            for value in (None, -1, True, "0"):
                with self.subTest(key=key, value=value):
                    anchor = json.loads(json.dumps(self.anchor))
                    anchor["counts"][key] = value
                    self.refused(anchor, key)

    def test_not_an_object_is_refused(self):
        self.refused([], "not a CVE report")

    def test_an_unknown_status_is_refused(self):
        self.anchor["status"] = "Fixed"
        self.refused(self.anchor, "unknown CVE status")

    def test_a_rescan_leaves_the_report_it_was_given_alone(self):
        before = json.dumps(self.anchor, sort_keys=True)
        build_report_from_anchor([self.manifest], self.anchor)
        self.assertEqual(json.dumps(self.anchor, sort_keys=True), before)


class CliTests(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        self.tree = rt.Tree(self.root)
        self.tree.pkg("libc6", "glibc", "2.43+git", "2.43+git1+5")
        self.tree.pkg("libz1", "zlib", "1.3.1")
        self.build_scan = self.tree.manifest("build", {"package": [
            entry("glibc", "2.43+git", issue("CVE-2026-1"))]})
        self.rescan = self.tree.manifest("rescan", {"package": [
            entry("glibc", "2.43+git", issue("CVE-2026-1"), issue("CVE-2026-2", "Patched")),
            entry("zlib", "1.3.1", issue("CVE-2026-3"))]})

    def run_main(self, *argv):
        err = io.StringIO()
        with mock.patch.object(sys, "argv", ["report"] + list(argv)), \
                contextlib.redirect_stderr(err):
            try:
                rc = report.main()
            except SystemExit as e:
                rc = e.code
        return rc, err.getvalue()

    def read(self, path):
        with open(path) as f:
            return normalized(json.load(f))

    def in_build_cli(self, manifest, out, *extra):
        rc, err = self.run_main(
            "--manifest", manifest, "--pkgdata-dir", self.tree.machine,
            "--machine", rt.MACHINE, "--status", "All", "-o", out, *extra)
        self.assertEqual(rc, 0, err)

    def test_the_cli_matches_the_in_build_cli(self):
        for extra in ((), ("--no-summary",)):
            with self.subTest(extra=extra):
                anchor = os.path.join(self.root, "anchor.json")
                self.in_build_cli(self.build_scan, anchor, *extra)
                want = os.path.join(self.root, "want.json")
                self.in_build_cli(self.rescan, want, *extra)

                got = os.path.join(self.root, "got.json")
                rc, err = self.run_main("--from-report", anchor, "--manifest", self.rescan,
                                        "-o", got)
                self.assertEqual(rc, 0, err)
                self.assertEqual(self.read(got), self.read(want))
                self.assertIn("all CVEs", err)

    def test_the_cli_rebuilds_a_version_one_report(self):
        anchor = rt.load_fixture("one-tree.json")
        tree = rt.Tree(os.path.join(self.root, "v1"))
        rt.one_tree(tree)
        path = os.path.join(self.root, "v1.json")
        with open(path, "w") as f:
            json.dump(anchor, f)
        out = os.path.join(self.root, "out.json")
        rescan = rt.one_tree_rescan(tree)
        rc, err = self.run_main("--from-report", path, "--manifest", rescan[0],
                                "--manifest", rescan[1], "-o", out)
        self.assertEqual(rc, 0, err)
        doc = self.read(out)
        self.assertEqual((doc["version"], doc["packages_digest"]),
                         ("2", anchor["packages_digest"]))

    def test_the_cli_refuses_a_version_one_report_with_alternates(self):
        path = os.path.join(self.root, "alt.json")
        with open(path, "w") as f:
            json.dump(rt.load_fixture("alternates.json"), f)
        out = os.path.join(self.root, "out.json")
        with open(out, "w") as f:
            f.write("stale")
        rc, err = self.run_main("--from-report", path, "--manifest", self.rescan, "-o", out)
        self.assertEqual(rc, 1)
        self.assertIn("alternate multiconfig", err)
        self.assertFalse(os.path.exists(out))

    def test_the_cli_never_writes_over_an_input(self):
        anchor = os.path.join(self.root, "anchor.json")
        self.in_build_cli(self.build_scan, anchor)
        with open(anchor, "rb") as f:
            before = f.read()
        alias = os.path.join(self.root, "alias.json")
        os.link(anchor, alias)
        for out in (anchor, self.rescan, alias):
            with self.subTest(out=out):
                rc, err = self.run_main("--from-report", anchor, "--manifest", self.rescan,
                                        "-o", out)
                self.assertEqual(rc, 2)
                self.assertIn("one of the inputs", err)
        with open(anchor, "rb") as f:
            self.assertEqual(f.read(), before)

    def test_the_cli_never_writes_its_temporary_file_over_an_input(self):
        anchor = os.path.join(self.root, "report.json.tmp")
        self.in_build_cli(self.build_scan, anchor)
        with open(anchor, "rb") as f:
            before = f.read()
        linked = os.path.join(self.root, "linked.json")
        os.symlink(anchor, linked + ".tmp")
        for out in (os.path.join(self.root, "report.json"), linked):
            with self.subTest(out=out):
                rc, err = self.run_main("--from-report", anchor, "--manifest", self.rescan,
                                        "-o", out)
                self.assertEqual(rc, 2)
                self.assertIn("one of the inputs", err)
        with open(anchor, "rb") as f:
            self.assertEqual(f.read(), before)

    def test_the_cli_removes_stale_output_when_the_anchor_is_unreadable(self):
        anchor = os.path.join(self.root, "anchor.json")
        with open(anchor, "w") as f:
            f.write('{"version": "2", "packages":')
        out = os.path.join(self.root, "out.json")
        with open(out, "w") as f:
            f.write("stale")
        rc, err = self.run_main("--from-report", anchor, "--manifest", self.rescan,
                                "-o", out)
        self.assertEqual(rc, 1)
        self.assertIn("cannot read", err)
        self.assertFalse(os.path.exists(out))

    def test_the_cli_refuses_an_unreadable_scan(self):
        anchor = os.path.join(self.root, "anchor.json")
        self.in_build_cli(self.build_scan, anchor)
        bad = self.tree.manifest("bad", "{")
        rc, err = self.run_main("--from-report", anchor, "--manifest", bad,
                                "-o", os.path.join(self.root, "out.json"))
        self.assertEqual(rc, 1)
        self.assertIn("failed to parse", err)

    def test_the_cli_refuses_build_tree_arguments(self):
        anchor = os.path.join(self.root, "anchor.json")
        self.in_build_cli(self.build_scan, anchor)
        for extra in (("--machine", "x"), ("--pkgdata-dir", self.tree.machine),
                      ("--tmpdir", self.root), ("--coverage", anchor),
                      ("--alt-pkgdata-dir", "mc:" + self.tree.machine),
                      ("--alt-recipe", "mc:glibc")):
            with self.subTest(extra=extra):
                rc, _ = self.run_main("--from-report", anchor, "--manifest",
                                      self.rescan, "-o", "o.json", *extra)
                self.assertEqual(rc, 2)
        rc, _ = self.run_main("--from-report", anchor, "-o", "o.json")
        self.assertEqual(rc, 2)

    def test_the_build_tree_cli_still_defaults_to_unpatched(self):
        out = os.path.join(self.root, "out.json")
        rc, err = self.run_main("--manifest", self.rescan, "--pkgdata-dir",
                                self.tree.machine, "-o", out)
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.read(out)["status"], "Unpatched")


if __name__ == "__main__":
    unittest.main()
