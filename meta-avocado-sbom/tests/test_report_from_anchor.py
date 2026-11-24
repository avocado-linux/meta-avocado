#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""Prove a report rebuilt from a previous report equals the one the build
would have written for the same scan.

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
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

from avocado_sbom import report  # noqa: E402
from avocado_sbom.report import (  # noqa: E402
    MANIFEST_SUFFIX,
    REPORT_STATUSES,
    build_report,
    build_report_from_anchor,
    write_report,
)

GENERATED = "2000-01-01T00:00:00Z"

def issue(cve, status="Unpatched", **extra):
    item = {"id": cve, "status": status, "summary": "s " + cve,
            "description": "d " + cve, "scorev3": "7.5", "link": "l"}
    item.update(extra)
    return item

def entry(name, version, *issues):
    return {"name": name, "version": version, "issue": list(issues)}

class Tree:
    """A build's pkgdata and the manifests of two scans of it."""

    def __init__(self, root):
        self.root = root
        self.machine = os.path.join(root, "pkgdata", "raspberrypi5")
        self.sdk = os.path.join(root, "pkgdata", "x86_64-avocadosdk-linux")
        for d in (self.machine, self.sdk):
            os.makedirs(os.path.join(d, "runtime-reverse"))
        self.dirs = [self.machine, self.sdk]
        self.alt = os.path.join(root, "tmp-alt", "pkgdata", "raspberrypi5")
        os.makedirs(os.path.join(self.alt, "runtime-reverse"))
        self.alt_trees = ()

    def pkg(self, name, text, sdk=False, alt=False):
        base = self.alt if alt else self.sdk if sdk else self.machine
        with open(os.path.join(base, "runtime-reverse", name), "w") as f:
            f.write(text)

    def manifest(self, name, data):
        path = os.path.join(self.root, name + MANIFEST_SUFFIX)
        with open(path, "w") as f:
            if isinstance(data, str):
                f.write(data)
            else:
                json.dump(data, f)
        return path

def normalized(doc):
    doc = dict(doc)
    doc["generated"] = GENERATED
    return doc

def as_bytes(doc, root):
    path = os.path.join(root, "out-%d.json" % random.getrandbits(64))
    write_report(normalized(doc), path)
    with open(path, "rb") as f:
        data = f.read()
    os.unlink(path)
    return data

def in_build(manifests, dirs, machine, status, summary, distro="2026.1", alt_trees=()):
    """What do_cve_report writes."""
    doc, stats = build_report(manifests, dirs, machine=machine,
                              status=status, summary=summary, alt_trees=alt_trees)
    if distro:
        doc["distro_version"] = distro
    return doc, stats

def round_trip(doc, root):
    """The anchor as the rescan gets it: the file the build uploaded."""
    path = os.path.join(root, "anchor.json")
    write_report(doc, path)
    with open(path) as f:
        return json.load(f)

class EquivalenceTests(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        self.tree = Tree(self.root)

    def populate(self):
        t = self.tree
        t.pkg("libc6", "PN: glibc\nPV: 2.43+git\nPKGV: 2.43+git1+562cd7badd\nPKGR: r0\n")
        t.pkg("glibc-utils", "PN: glibc\nPV: 2.43+git\nPKGV: 2.43+git0+562cd7badd\nPKGR: r0\n")
        t.pkg("kernel-image", "PN: linux-raspberrypi\nPV: 6.12.87+git\n"
              "PKGV: 6.12.87+git0+abc\nPKGR: r0\n")
        t.pkg("libssl3", "PN: openssl\nPV: 3.5.7\nPKGV: 3.5.7\nPKGR: r0\n")
        t.pkg("libz1", "PN: zlib\nPV: 1.3.1\nPKGV: 1.3.1\nPKGR: r0\n")
        t.pkg("libattr1", "PN: attr\nPV: 2.5.2\nPKGV: 2.5.2\nPKGR: r0\n")
        t.pkg("libdevmapper", "PN: lvm2\nPV: 2.03.39\nPKGV:libdevmapper: 1.02.213\n"
              "PKGR:libdevmapper: r0.3\n")
        t.pkg("dbus", "PN: dbus\nPV: 1.16.2\nPKGV: 1.16.2\nPKGR: r0\n")
        # No version at all: kept out of recipe_versions, still "packaged".
        t.pkg("packagegroup-x", "PN: packagegroup-x\n")
        # Unreadable, and a name the SDK directory claims for another recipe.
        t.pkg("broken", "garbage\n")
        t.pkg("libssl3", "PN: openssl-vendor\nPV: 1.1.1w\nPKGV: 1.1.1w\nPKGR: r0\n", sdk=True)
        t.pkg("nativesdk-libz1", "PN: nativesdk-zlib\nPV: 1.3.1\nPKGV: 1.3.1\nPKGR: r0\n", sdk=True)

        self.build_scan = t.manifest("build", {"package": [
            entry("glibc", "2.43+git", issue("CVE-2026-1"), issue("CVE-2025-9", "Patched")),
            entry("linux-raspberrypi", "6.12.87+git", issue("CVE-2026-10")),
            entry("openssl", "3.5.7", issue("CVE-2026-2", "Ignored")),
            entry("zlib", "1.3.1"),
            entry("openssl-vendor", "1.1.1w"),
            entry("dbus", "1_1.16.2", issue("CVE-2026-20")),
        ]})
        # A later scan: new CVEs, changed statuses, a newly scanned recipe, a
        # stale entry, an unknown recipe, an EXTENDPE prefix, an unpackaged
        # recipe and its CVEs, an unknown status, a malformed entry, a repeat
        # across two manifests and an unreadable third one.
        self.rescan = [
            t.manifest("rescan-a", {"package": [
                entry("glibc", "2.43+git", issue("CVE-2026-1", "Patched"),
                      issue("CVE-2026-30"), issue("CVE-2026-31", "Ignored")),
                entry("linux-raspberrypi", "6.12.87+git", issue("CVE-2026-10"),
                      issue("CVE-2026-11"), issue("CVE-2026-12", "Patched")),
                entry("openssl", "3.5.6", issue("CVE-2026-40")),
                entry("zlib", "1.3.1", issue("CVE-2026-50", "Foo")),
                entry("attr", "2.5.2", issue("CVE-2026-60")),
                entry("openssl-vendor", "1.1.1w", issue("CVE-2026-70")),
                entry("dbus", "1_1.16.2", issue("CVE-2026-20"), issue("CVE-2026-21")),
                entry("packagegroup-x", "1.0", issue("CVE-2026-80")),
                entry("busybox-native", "1.37", issue("CVE-2026-90")),
                {"name": 7, "version": "1"},
                entry("lvm2", "2.03.39", {"id": "CVE-2026-91"}),
            ]}),
            t.manifest("rescan-b", {"package": [
                entry("glibc", "2.43+git", issue("CVE-2026-30"), issue("CVE-2026-32")),
            ]}),
            t.manifest("rescan-c", "{not json"),
        ]

    def assert_equivalent(self, status, summary, anchor_status="All"):
        self.populate()
        anchor_doc, _ = in_build([self.build_scan], self.tree.dirs,
                                 "raspberrypi5", anchor_status, True)
        anchor = round_trip(anchor_doc, self.root)

        want, want_stats = in_build(self.rescan, self.tree.dirs,
                                    "raspberrypi5", status, summary)
        got, got_stats = build_report_from_anchor(
            self.rescan, anchor, status=status, summary=summary)

        self.assertEqual(as_bytes(got, self.root), as_bytes(want, self.root))
        self.assertEqual(dict(got_stats), dict(want_stats))
        return got

    def test_every_status_and_summary_gives_the_same_bytes(self):
        for status in REPORT_STATUSES:
            for summary in (True, False):
                with self.subTest(status=status, summary=summary):
                    self.setUp()
                    self.assert_equivalent(status, summary)

    def test_the_fixture_exercises_every_path(self):
        doc = self.assert_equivalent("All", True)
        counts = doc["counts"]
        for key in ("stale_dropped", "unscanned_recipes", "cve_files_unreadable",
                    "entries_unreadable", "pkgdata_unreadable",
                    "package_collisions", "unknown_status_cves",
                    "patched_cves", "ignored_cves"):
            self.assertGreater(counts[key], 0, key)
        self.assertIs(doc["recipes"]["packagegroup-x"]["packaged"], True)
        self.assertIs(doc["recipes"]["openssl-vendor"]["packaged"], True)
        self.assertIs(doc["recipes"]["busybox-native"]["packaged"], False)
        self.assertIn("glibc", doc["recipes"])
        self.assertNotIn("openssl", doc["recipes"])
        self.assertEqual(doc["recipes"]["dbus"]["version"], "1.16.2")
        self.assertEqual(doc["machine"], "raspberrypi5")
        self.assertEqual(doc["distro_version"], "2026.1")

    def test_status_defaults_to_the_anchors(self):
        self.populate()
        anchor = round_trip(in_build([self.build_scan], self.tree.dirs,
                                     "raspberrypi5", "Patched", True)[0], self.root)
        doc, _ = build_report_from_anchor(self.rescan, anchor)
        self.assertEqual(doc["status"], "Patched")

    def test_no_machine_or_distro_version_stays_absent(self):
        self.populate()
        anchor = round_trip(in_build([self.build_scan], self.tree.dirs,
                                     None, "All", True, distro=None)[0], self.root)
        want, _ = in_build(self.rescan, self.tree.dirs, None, "All", True, distro=None)
        got, _ = build_report_from_anchor(self.rescan, anchor)
        self.assertNotIn("machine", got)
        self.assertNotIn("distro_version", got)
        self.assertEqual(as_bytes(got, self.root), as_bytes(want, self.root))

class RandomizedEquivalenceTests(unittest.TestCase):
    """Generated builds and scans, seeded so a failure reproduces."""

    VERSIONS = ("1.0", "2.43+git", "6.12.87+git", "3.5.7", "0.9.1")
    STATUSES = ("Unpatched", "Patched", "Ignored", "Unpatched", "Bogus", None)

    def generate(self, rng, root):
        tree = Tree(root)
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
                tree.pkg("%s-%d" % (r, i), text)
                if rng.random() < 0.15:
                    other = rng.choice(recipes) + "-sdk"
                    tree.pkg("%s-%d" % (r, i),
                             "PN: %s\nPV: 1.0\nPKGV: 1.0\nPKGR: r0\n" % other, sdk=True)

        # An alternate multiconfig: some recipes again at another version, some
        # at the same one, one only it builds, and names both trees package.
        alt_pv = {}
        if rng.random() < 0.5:
            for r in rng.sample(recipes, rng.randint(1, len(recipes))):
                alt_pv[r] = rng.choice(self.VERSIONS + ("9.9-alt", "7.7-alt"))
            alt_pv["alt-only"] = "4.2"
            for r, v in alt_pv.items():
                for i in range(rng.randint(1, 3)):
                    name = "%s-%d" % (r, i) if rng.random() < 0.3 else "%s-%s-%d" % (r, v, i)
                    tree.pkg(name, "PN: %s\nPV: %s\nPKGV: %s\nPKGR: r%d\n" % (r, v, v, i),
                             alt=True)
            named = set(alt_pv) if rng.random() < 0.7 else None
            tree.alt_trees = [(tree.alt, named)]

        def scan(name):
            names = recipes + ["%s-sdk" % r for r in recipes] + ["stray"]
            names += ["%s@alt" % r for r in alt_pv]
            entries = []
            for n in rng.sample(names, rng.randint(0, len(names))):
                if n.endswith("@alt"):
                    n = n[:-len("@alt")]
                    v = alt_pv[n]
                else:
                    v = pv.get(n, "1.0")
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
        return tree, scan("build"), manifests

    def assert_accounted(self, doc, seed):
        """At All, every shipped recipe is in exactly one list, and every
        package whose recipe has a record carries the version of one."""
        lists = (set(doc["recipes"]), set(doc["no_cve_record_recipes"]),
                 set(doc["unscanned_recipes"]))
        for pkg in doc["packages"].values():
            recipe = pkg["recipe"]
            self.assertEqual(sum(recipe in each for each in lists), 1,
                             "seed %d: %s" % (seed, recipe))
            version = pkg.get("recipe_version")
            if version is not None:
                record = doc["recipes"][recipe]
                self.assertIn(version, [r["version"] for r in
                                        [record] + record.get("alt_versions", [])],
                              "seed %d: %s" % (seed, recipe))

    def test_generated_builds(self):
        with_alt = 0
        for seed in range(300):
            rng = random.Random(seed)
            root = tempfile.mkdtemp()
            try:
                tree, build_scan, manifests = self.generate(rng, root)
                status = rng.choice(REPORT_STATUSES)
                summary = rng.random() < 0.5
                anchor_doc, stats = in_build([build_scan], tree.dirs, "m",
                                             rng.choice(REPORT_STATUSES), True,
                                             alt_trees=tree.alt_trees)
                if not stats.packages:
                    continue
                anchor = round_trip(anchor_doc, root)
                want, want_stats = in_build(manifests, tree.dirs, "m", status, summary,
                                            alt_trees=tree.alt_trees)
                got, got_stats = build_report_from_anchor(
                    manifests, anchor, status=status, summary=summary)
                self.assertEqual(as_bytes(got, root), as_bytes(want, root),
                                 "seed %d" % seed)
                self.assertEqual(dict(got_stats), dict(want_stats), "seed %d" % seed)
                if tree.alt_trees and want["alt_packages"]:
                    with_alt += 1
                if status == "All":
                    self.assert_accounted(want, seed)
            finally:
                shutil.rmtree(root)
        self.assertGreater(with_alt, 30)

class AnchorRefusalTests(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        self.tree = Tree(self.root)
        self.tree.pkg("libz1", "PN: zlib\nPV: 1.3.1\nPKGV: 1.3.1\nPKGR: r0\n")
        self.manifest = self.tree.manifest(
            "m", {"package": [entry("zlib", "1.3.1", issue("CVE-2026-1"))]})
        self.anchor = round_trip(
            build_report([self.manifest], self.tree.dirs, machine="m", status="All")[0],
            self.root)

    def refused(self, anchor, words):
        with self.assertRaises(ValueError) as ctx:
            build_report_from_anchor([self.manifest], anchor)
        self.assertIn(words, str(ctx.exception))

    def test_a_report_without_recipe_versions_is_refused(self):
        del self.anchor["recipe_versions"]
        self.refused(self.anchor, "scanned before the report carried them")

    def test_an_empty_recipe_versions_is_accepted(self):
        self.anchor["recipe_versions"] = {}
        doc, _ = build_report_from_anchor([self.manifest], self.anchor)
        self.assertIs(doc["recipes"]["zlib"]["packaged"], True)

    def test_another_report_version_is_refused(self):
        self.anchor["version"] = "2"
        self.refused(self.anchor, "report version")

    def test_edited_packages_are_refused(self):
        self.anchor["packages"]["libz1"]["version"] = "1.3.2-r0"
        self.refused(self.anchor, "packages_digest")

    def test_malformed_parts_are_refused(self):
        cases = (
            ("packages", {}, "packages"),
            ("packages", {"libz1": {"recipe": "zlib"}}, "packages"),
            ("recipe_versions", {"zlib": "1.3.1"}, "recipe_versions"),
            ("recipe_versions", {"zlib": []}, "recipe_versions"),
            ("counts", None, "counts"),
            ("machine", ["m"], "machine"),
            ("machine", "", "machine"),
            ("distro_version", {"v": 1}, "distro_version"),
            ("machine", None, "machine"),
        )
        for key, value, words in cases:
            with self.subTest(key=key, value=value):
                anchor = json.loads(json.dumps(self.anchor))
                anchor[key] = value
                self.refused(anchor, words)
        for key in ("pkgdata_unreadable", "package_collisions"):
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

class CliTests(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        self.tree = Tree(self.root)
        self.tree.pkg("libc6", "PN: glibc\nPV: 2.43+git\nPKGV: 2.43+git1+5\nPKGR: r0\n")
        self.tree.pkg("libz1", "PN: zlib\nPV: 1.3.1\nPKGV: 1.3.1\nPKGR: r0\n")
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

    def in_build_cli(self, manifest, out, status="All"):
        rc, err = self.run_main(
            "--manifest", manifest, "--pkgdata-dir", self.tree.machine,
            "--machine", "raspberrypi5", "--status", status, "-o", out)
        self.assertEqual(rc, 0, err)

    def test_the_cli_matches_the_in_build_cli(self):
        anchor = os.path.join(self.root, "anchor.json")
        self.in_build_cli(self.build_scan, anchor)
        want = os.path.join(self.root, "want.json")
        self.in_build_cli(self.rescan, want)

        got = os.path.join(self.root, "got.json")
        rc, err = self.run_main("--from-report", anchor, "--manifest", self.rescan,
                                "-o", got)
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.read(got), self.read(want))
        self.assertIn("all CVEs", err)

    def test_the_cli_refuses_a_report_without_recipe_versions(self):
        anchor = os.path.join(self.root, "anchor.json")
        self.in_build_cli(self.build_scan, anchor)
        with open(anchor) as f:
            doc = json.load(f)
        del doc["recipe_versions"]
        with open(anchor, "w") as f:
            json.dump(doc, f)
        out = os.path.join(self.root, "out.json")
        with open(out, "w") as f:
            f.write("stale")
        rc, err = self.run_main("--from-report", anchor, "--manifest", self.rescan,
                                "-o", out)
        self.assertEqual(rc, 1)
        self.assertIn("recipe_versions", err)
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
            f.write('{"version": "1", "packages":')
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
                      ("--tmpdir", self.root)):
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
