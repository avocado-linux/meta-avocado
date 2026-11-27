#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""Prove what a consumer binds each RPM to: its package build, by name and
version-release, and that build's own record, for builds of one recipe in
several multiconfigs, at one version or another, kept in the feed document or
left out of it.

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
import report_trees as rt  # noqa: E402
from avocado_sbom import feedsbom, report  # noqa: E402
from avocado_sbom.report import build_report, build_report_from_anchor  # noqa: E402
from report_trees import entry, issue, round_trip  # noqa: E402

SCHEMA = os.path.join(HERE, "..", "schema", "avocado-cve-report-v2.schema.json")
OOT = "nvidia-kernel-oot"
ARCH = "jetson"


def rpm(name, version, release, arch=ARCH):
    return {"name": name, "version": version, "release": release, "arch": arch}


class JetsonTests(unittest.TestCase):
    """Jetson AGX Orin: the default multiconfig's linux-yocto and three
    alternate multiconfigs' kernels, each with its own nvidia-kernel-oot at
    one recipe version. A PR server gives each multiconfig's build its own
    release, so nvidia-kernel-oot-base is four RPMs of one name; the kernels
    all package "kernel" and "kernel-dev", the stock and RT kernels at one
    version, and kernel-devsrc is 1.0 in every tree."""

    # (mc, kernel recipe, kernel version, release of the trees' own builds)
    TREES = (("", "linux-yocto", "6.18.52", "r0.1"),
             ("jetson-l4t", "linux-noble-nvidia-tegra", "6.8.12", "r0.2"),
             ("jetson-rt", "linux-yocto-rt", "6.18.52", "r0.3"),
             ("jetson-l4t-rt", "linux-noble-nvidia-tegra-rt", "6.8.12", "r0.4"))

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        self.tree = rt.Tree(self.root, machine=ARCH)
        self.rpms = []
        for mc, kernel, kver, release in self.TREES:
            if mc:
                self.tree.alt(mc, {kernel, OOT, "kernel-devsrc"})
            suffix = "-" + mc if mc else ""
            for name in ("kernel", "kernel-dev", "kernel-image-%s%s" % (kver, suffix)):
                self.pkg(name, kernel, kver + "+git", release, mc)
            for name in ("nvidia-kernel-oot-base", "nv-kernel-module-x-%s%s" % (kver, suffix)):
                self.pkg(name, OOT, "39.2.1", release, mc)
            self.pkg("kernel-devsrc", "kernel-devsrc", "1.0", release, mc)
        self.scan = self.tree.manifest("feed", {"package": [
            entry("linux-yocto", "6.18.52+git", issue("CVE-2026-1")),
            entry("jetson-l4t:linux-noble-nvidia-tegra", "6.8.12+git", issue("CVE-2026-2")),
            entry("jetson-rt:linux-yocto-rt", "6.18.52+git", issue("CVE-2026-1"),
                  issue("CVE-2026-3", "Patched", detail="backported-patch")),
            entry("jetson-l4t-rt:linux-noble-nvidia-tegra-rt", "6.8.12+git",
                  issue("CVE-2026-2"), issue("CVE-2026-4")),
            # One per build, the same CVEs in each: they share product and
            # statements, or the feed document left them out.
            entry(OOT, "39.2.1", issue("CVE-2026-7")),
            entry("jetson-l4t:" + OOT, "39.2.1", issue("CVE-2026-7")),
            entry("jetson-rt:" + OOT, "39.2.1", issue("CVE-2026-7")),
            entry("jetson-l4t-rt:" + OOT, "39.2.1", issue("CVE-2026-7")),
            entry("kernel-devsrc", "1.0"),
            entry("jetson-l4t:kernel-devsrc", "1.0"),
            entry("jetson-rt:kernel-devsrc", "1.0"),
            entry("jetson-l4t-rt:kernel-devsrc", "1.0"),
        ]})

    def pkg(self, name, recipe, pv, release, mc):
        self.tree.pkg(name, recipe, pv, pkgr=release, mc=mc)
        self.rpms.append(rpm(name, pv, release))

    def build(self, not_covered=None):
        doc, stats = build_report([self.scan], self.tree.dirs, machine=ARCH, status="All",
                                  alt_trees=self.tree.alt_trees, not_covered=not_covered)
        return doc, stats

    def test_every_rpm_joins_its_own_build(self):
        doc, stats = self.build()
        verdicts = binding_rules.rpm_verdicts(doc, {"packages": self.rpms})
        self.assertEqual(len(verdicts), len(self.rpms))
        cves = {"linux-yocto": {"CVE-2026-1": "affected"},
                "linux-noble-nvidia-tegra": {"CVE-2026-2": "affected"},
                "linux-yocto-rt": {"CVE-2026-1": "affected", "CVE-2026-3": "patched"},
                "linux-noble-nvidia-tegra-rt": {"CVE-2026-2": "affected",
                                                "CVE-2026-4": "affected"}}
        for mc, kernel, kver, release in self.TREES:
            suffix = "-" + mc if mc else ""
            for name in ("kernel", "kernel-dev", "kernel-image-%s%s" % (kver, suffix)):
                self.assertEqual(verdicts[(name, kver + "+git", release, ARCH)],
                                 ("checked", cves[kernel]), (mc, name))
            for name in ("nvidia-kernel-oot-base", "nv-kernel-module-x-%s%s" % (kver, suffix)):
                self.assertEqual(verdicts[(name, "39.2.1", release, ARCH)],
                                 ("checked", {"CVE-2026-7": "affected"}), (mc, name))
            self.assertEqual(verdicts[("kernel-devsrc", "1.0", release, ARCH)],
                             ("not_checked", "no-cve-record"))
        self.assertEqual([k for k, v in verdicts.items() if v[0] == "not_checked"],
                         [k for k in verdicts if k[0] == "kernel-devsrc"])
        self.assertEqual(stats.stale_dropped, 0)

    def test_each_build_is_its_own_record(self):
        doc, _ = self.build()
        builds = doc["builds"]
        for mc, _kernel, _kver, _release in self.TREES:
            bid = report.build_id(mc, OOT)
            self.assertEqual((builds[bid]["recipe"], builds[bid]["mc"], builds[bid]["version"],
                              builds[bid]["version_keys"], builds[bid]["coverage"]),
                             (OOT, mc, "39.2.1", ["39.2.1"], "scanned"))
            self.assertEqual([c["id"] for c in builds[bid]["cves"]], ["CVE-2026-7"])
        self.assertEqual(doc["counts"]["builds"], 12)
        self.assertEqual(doc["counts"]["alternate_builds"], 9)
        self.assertEqual(doc["packages"]["nvidia-kernel-oot-base"], [
            {"version": "39.2.1-r0.%d" % n, "build": report.build_id(mc, OOT)}
            for n, (mc, _k, _v, _r) in enumerate(self.TREES, 1)])
        self.assertEqual(doc["packages"]["kernel"], [
            {"version": "6.18.52+git-r0.1", "build": "linux-yocto"},
            {"version": "6.18.52+git-r0.3", "build": "jetson-rt:linux-yocto-rt"},
            {"version": "6.8.12+git-r0.2", "build": "jetson-l4t:linux-noble-nvidia-tegra"},
            {"version": "6.8.12+git-r0.4", "build": "jetson-l4t-rt:linux-noble-nvidia-tegra-rt"}])
        self.assertEqual(doc["packages"]["kernel-devsrc"], [
            {"version": "1.0-r0.%d" % n, "build": report.build_id(mc, "kernel-devsrc")}
            for n, (mc, _k, _v, _r) in enumerate(self.TREES, 1)])
        self.assertEqual((doc["counts"]["shared_package_builds"],
                          doc["counts"]["package_collisions"]), (0, 0))

    def test_a_left_out_alternates_packages_are_not_covered_never_the_defaults(self):
        # The regression: an alternate of a recipe the default also built, at
        # the default's version, left out of the document. Its distinct names
        # once took the default's record and bound checked with its verdicts.
        reason = "VEX overlap: jetson_linux 39.2.1 is also nvidia-kernel-oot, with other " \
                 "statements on CVE-2026-9"
        with open(self.scan) as f:
            data = json.load(f)
        data["package"] = [e for e in data["package"] if e["name"] != "jetson-rt:" + OOT]
        with open(self.scan, "w") as f:
            json.dump(data, f)
        doc, stats = self.build(not_covered={"jetson-rt:" + OOT: reason})
        left_out = doc["builds"]["jetson-rt:" + OOT]
        self.assertEqual((left_out["coverage"], left_out["not_covered"]), ("unscanned", reason))
        self.assertNotIn("cves", left_out)
        verdicts = binding_rules.rpm_verdicts(doc, {"packages": self.rpms})
        for name in ("nv-kernel-module-x-6.18.52-jetson-rt", "nvidia-kernel-oot-base"):
            self.assertEqual(verdicts[(name, "39.2.1", "r0.3", ARCH)],
                             ("not_checked", "build-not-covered"))
        self.assertEqual(verdicts[("nvidia-kernel-oot-base", "39.2.1", "r0.1", ARCH)],
                         ("checked", {"CVE-2026-7": "affected"}))
        self.assertEqual(stats.not_covered_builds, 1)

    def test_a_document_that_does_not_name_alternates_leaves_them_unscanned(self):
        # A scan of a document from before the alternates were named: their
        # entries file under the default build of their name, or under a
        # build of their own with no package data, so the alternate builds
        # stay unscanned rather than take a record that is not theirs.
        scan = self.tree.manifest("plain", {"package": [
            entry(kernel, kver + "+git", issue("CVE-2026-1"))
            for _mc, kernel, kver, _r in self.TREES] + [entry(OOT, "39.2.1")] * 4})
        doc, stats = build_report([scan], self.tree.dirs, status="All",
                                  alt_trees=self.tree.alt_trees)
        self.assertEqual(doc["builds"]["jetson-rt:" + OOT]["coverage"], "unscanned")
        self.assertEqual(doc["builds"]["jetson-rt:linux-yocto-rt"]["coverage"], "unscanned")
        self.assertEqual(doc["builds"][OOT]["coverage"], "no-cve-record")
        # Same recipe name only in an alternate: an entry under the plain name
        # is a build of its own, unpackaged, and binds nothing.
        self.assertIs(doc["builds"]["linux-yocto-rt"]["packaged"], False)
        self.assertEqual(stats.stale_dropped, 0)

    def test_two_rpms_of_one_package_build_are_ambiguous(self):
        doc, _ = self.build()
        rpms = self.rpms + [rpm("nvidia-kernel-oot-base", "39.2.1", "r0.1", "armv8a")]
        verdicts = binding_rules.rpm_verdicts(doc, {"packages": rpms})
        for arch in (ARCH, "armv8a"):
            self.assertEqual(verdicts[("nvidia-kernel-oot-base", "39.2.1", "r0.1", arch)],
                             ("not_checked", "ambiguous-version"))

    def test_an_rpm_with_no_package_build_rejects_the_upload(self):
        doc, _ = self.build()
        for extra in (rpm("nvidia-kernel-oot-base", "39.2.1", "r0.9"), rpm("stray", "1", "r0")):
            with self.subTest(extra=extra):
                with self.assertRaises(binding_rules.Rejected):
                    binding_rules.rpm_verdicts(doc, {"packages": self.rpms + [extra]})

    def test_a_rebuild_from_the_report_binds_the_same(self):
        doc, _ = self.build(not_covered={"jetson-l4t-rt:" + OOT: "why"})
        again, _ = build_report_from_anchor([self.scan], round_trip(doc, self.root))
        manifest = {"packages": self.rpms}
        self.assertEqual(binding_rules.rpm_verdicts(again, manifest),
                         binding_rules.rpm_verdicts(doc, manifest))


class SameVersionTests(unittest.TestCase):
    """Builds of one recipe at one version in two multiconfigs."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        self.tree = rt.Tree(self.root)

    def test_a_compiled_source_alternate_at_the_defaults_version_keeps_its_own_record(self):
        # The compiled-source filter makes two builds at one version differ.
        self.tree.alt("mc-rt", {"linux-yocto"})
        self.tree.pkg("kernel-image-6.18.52", "linux-yocto", "6.18.52", pkgr="r0.1")
        self.tree.pkg("kernel-image-6.18.52", "linux-yocto", "6.18.52", pkgr="r0.2", mc="mc-rt")
        filtered = dict(detail=report.COMPILED_SOURCE_DETAIL,
                        description=report.COMPILED_SOURCE_DESCRIPTION)
        scan = self.tree.manifest("feed", {"package": [
            dict(entry("linux-yocto", "6.18.52", issue("CVE-2026-1", "Ignored", **filtered),
                       issue("CVE-2026-2")), products=[{"product": "linux_kernel"}]),
            dict(entry("mc-rt:linux-yocto", "6.18.52", issue("CVE-2026-1"),
                       issue("CVE-2026-2", "Ignored", **filtered)),
                 products=[{"product": "linux_kernel"}]),
        ]})
        doc, _ = build_report([scan], self.tree.dirs, status="All",
                              alt_trees=self.tree.alt_trees, compiled_sources={"linux-yocto"})
        verdicts = binding_rules.rpm_verdicts(doc, {"packages": [
            rpm("kernel-image-6.18.52", "6.18.52", "r0.1"),
            rpm("kernel-image-6.18.52", "6.18.52", "r0.2")]})
        self.assertEqual(verdicts[("kernel-image-6.18.52", "6.18.52", "r0.1", ARCH)],
                         ("checked", {"CVE-2026-2": "affected"}))
        self.assertEqual(verdicts[("kernel-image-6.18.52", "6.18.52", "r0.2", ARCH)],
                         ("checked", {"CVE-2026-1": "affected"}))
        self.assertIs(doc["builds"]["mc-rt:linux-yocto"]["compiled_sources"], True)

    def test_compiled_source_trust_is_per_build_through_a_rebuild(self):
        # The default kernel lists its compiled sources and the alternate build
        # of the same recipe does not: the alternate's filtered CVE stays
        # unverified at build time and in every rebuild.
        self.tree.alt("mc-rt", {"linux-yocto"})
        self.tree.pkg("kernel-image-6.18.52", "linux-yocto", "6.18.52", pkgr="r0.1")
        self.tree.pkg("kernel-image-6.18.52", "linux-yocto", "6.18.52", pkgr="r0.2", mc="mc-rt")
        filtered = dict(detail=report.COMPILED_SOURCE_DETAIL,
                        description=report.COMPILED_SOURCE_DESCRIPTION)
        scan = self.tree.manifest("feed", {"package": [
            dict(entry(name, "6.18.52", issue("CVE-2026-1", "Ignored", **filtered)),
                 products=[{"product": "linux_kernel"}])
            for name in ("linux-yocto", "mc-rt:linux-yocto")]})
        asked = []

        def opted_in(mc, recipe):
            asked.append((mc, recipe))
            return not mc
        built, _ = build_report([scan], self.tree.dirs, status="All",
                                alt_trees=self.tree.alt_trees, compiled_sources=opted_in)
        self.assertEqual(sorted(asked), [("", "linux-yocto"), ("mc-rt", "linux-yocto")])
        anchor = round_trip(built, self.root)
        rebuilt, _ = build_report_from_anchor([scan], anchor)
        for doc in (built, rebuilt):
            builds = doc["builds"]
            self.assertIs(builds["linux-yocto"]["compiled_sources"], True)
            self.assertIs(builds["mc-rt:linux-yocto"]["compiled_sources"], False)
            self.assertEqual(builds["linux-yocto"]["cves"][0]["status"], "Ignored")
            alt = builds["mc-rt:linux-yocto"]["cves"][0]
            self.assertEqual(alt["status"], "Unpatched")
            self.assertIn("scanner", alt)
        rebuilt["generated"] = anchor["generated"]
        self.assertEqual(round_trip(rebuilt, self.root), anchor)

    def shared_nevra(self, not_covered, default=False, scanned=("foo", "mc-a:foo", "mc-b:foo"),
                     merge_order=()):
        for mc in ("mc-a", "mc-b"):
            self.tree.alt(mc, {"foo"})
            self.tree.pkg("foo-base", "foo", "1.0", mc=mc)
        if default:
            self.tree.pkg("foo-base", "foo", "1.0")
        scan = self.tree.manifest("feed", {"package": [
            entry(name, "1.0", issue("CVE-2026-5")) for name in scanned
            if name not in not_covered]})
        doc, stats = build_report([scan], self.tree.dirs, status="All",
                                  alt_trees=self.tree.alt_trees, not_covered=not_covered,
                                  merge_order=merge_order)
        return doc, stats

    def verdict(self, doc):
        verdicts = binding_rules.rpm_verdicts(doc, {"packages": [rpm("foo-base", "1.0", "r0")]})
        return list(verdicts.values())

    def test_the_same_nevra_in_two_alternates_is_the_first_ones(self):
        # The multikernel merge never replaces a file in the feed, so the
        # feed serves the first alternate's.
        doc, stats = self.shared_nevra({})
        self.assertEqual(doc["packages"]["foo-base"], [{"version": "1.0-r0", "build": "mc-a:foo"}])
        self.assertEqual(stats.shared_package_builds, 1)

    def test_the_first_is_the_first_the_merge_publishes(self):
        doc, _ = self.shared_nevra({}, merge_order=["mc-b:foo", "mc-a:foo"])
        self.assertEqual(doc["packages"]["foo-base"], [{"version": "1.0-r0", "build": "mc-b:foo"}])

    def test_the_first_alternate_left_out_still_owns_the_file_and_is_not_covered(self):
        # The second alternate's record describes another build's bytes.
        doc, _ = self.shared_nevra({"mc-a:foo": "unresolved reference: 1 identifier(s)"})
        self.assertEqual(doc["packages"]["foo-base"], [{"version": "1.0-r0", "build": "mc-a:foo"}])
        self.assertEqual(self.verdict(doc), [("not_checked", "build-not-covered")])

    def test_the_same_nevra_the_default_built_is_the_defaults(self):
        doc, stats = self.shared_nevra({}, default=True)
        self.assertEqual(doc["packages"]["foo-base"], [{"version": "1.0-r0", "build": "foo"}])
        self.assertEqual(stats.shared_package_builds, 2)
        self.assertEqual(self.verdict(doc), [("checked", {"CVE-2026-5": "affected"})])
        # Even when the default build is unscanned and an alternate is scanned.
        doc, _ = self.shared_nevra({}, default=True, scanned=("mc-a:foo", "mc-b:foo"))
        self.assertEqual(doc["packages"]["foo-base"][0]["build"], "foo")
        self.assertEqual(self.verdict(doc), [("not_checked", "build-unscanned")])

    def test_the_same_name_and_version_from_another_recipe_is_a_collision(self):
        self.tree.alt("mc-a", {"bar"})
        self.tree.pkg("libx", "foo", "1.0")
        self.tree.pkg("libx", "bar", "1.0", mc="mc-a")
        scan = self.tree.manifest("feed", {"package": [entry("foo", "1.0")]})
        doc, stats = build_report([scan], self.tree.dirs, status="All",
                                  alt_trees=self.tree.alt_trees)
        self.assertEqual(doc["packages"]["libx"], [{"version": "1.0-r0", "build": "foo"}])
        self.assertEqual((stats.package_collisions, stats.shared_package_builds), (1, 0))

    def test_a_plus_and_a_hyphen_are_one_version(self):
        # The consumer compares versions with "+" read as "-".
        self.tree.alt("mc-a", {"foo"})
        self.tree.pkg("foo-base", "foo", "1.0+git", pkgr="r0")
        self.tree.pkg("foo-base", "foo", "1.0-git", pkgr="r0", mc="mc-a")
        doc, stats = build_report([self.tree.manifest("s", {"package": []})], self.tree.dirs,
                                  status="All", alt_trees=self.tree.alt_trees)
        self.assertEqual(doc["packages"]["foo-base"],
                         [{"version": "1.0+git-r0", "build": "foo"}])
        self.assertEqual(stats.shared_package_builds, 1)


class RaspberryPiTests(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        self.tree = rt.Tree(self.root)
        rt.rpi_kernels(self.tree)
        self.alt = "%s:linux-raspberrypi" % rt.RPI_MC
        self.scan = self.tree.manifest("feed", {"package": [
            entry("linux-raspberrypi", rt.DEFAULT_KERNEL, issue("CVE-2026-1"),
                  issue("CVE-2026-2", "Patched", detail="fixed-version: 6.12.50")),
            # The same id in both kernels: one record each, never merged.
            entry(self.alt, rt.ALT_KERNEL, issue("CVE-2026-1"), issue("CVE-2026-3")),
            entry("kernel-devsrc", rt.DEFAULT_KERNEL),
            entry("%s:kernel-devsrc" % rt.RPI_MC, rt.ALT_KERNEL),
            entry("openssl", "3.5.7", issue("CVE-2026-9")),
            entry("base-files", "3.0.14"),
        ]})

    def build(self, alt=True, status="All"):
        return build_report([self.scan], self.tree.dirs, machine="m", status=status,
                            alt_trees=self.tree.alt_trees if alt else ())

    def test_each_kernel_is_its_own_build(self):
        doc, stats = self.build()
        self.assertEqual([c["id"] for c in doc["builds"]["linux-raspberrypi"]["cves"]],
                         ["CVE-2026-1", "CVE-2026-2"])
        self.assertEqual(doc["builds"][self.alt]["cves"],
                         [dict(issue("CVE-2026-1"), status="Unpatched"),
                          dict(issue("CVE-2026-3"), status="Unpatched")])
        self.assertEqual(stats.stale_dropped, 0)
        counts = doc["counts"]
        self.assertEqual(counts["cves"], 5)
        self.assertEqual(counts["unpatched_cves"] + counts["patched_cves"]
                         + counts["ignored_cves"], counts["cves"])

    def test_both_kernels_shared_names_are_checked(self):
        doc, _ = self.build()
        for name in ("kernel", "kernel-dev"):
            self.assertEqual(binding_rules.package_verdict(doc, name, rt.DEFAULT_KERNEL + "-r0"),
                             ("checked", {"CVE-2026-1": "affected", "CVE-2026-2": "patched"}))
            self.assertEqual(binding_rules.package_verdict(doc, name, rt.ALT_KERNEL + "-r0"),
                             ("checked", {"CVE-2026-1": "affected", "CVE-2026-3": "affected"}))
        self.assertEqual(binding_rules.package_verdict(doc, "kernel-module-foo-6.6.78",
                                                       rt.ALT_KERNEL + "-r0"),
                         ("checked", {"CVE-2026-1": "affected", "CVE-2026-3": "affected"}))
        self.assertEqual(binding_rules.package_verdict(doc, "libssl3", "3.5.7-r0"),
                         ("checked", {"CVE-2026-9": "affected"}))

    def test_only_the_named_recipes_are_read_from_the_alternate_tree(self):
        doc, _ = self.build()
        self.assertNotIn("alt-only-tool", doc["packages"])
        self.assertNotIn("%s:base-files" % rt.RPI_MC, doc["builds"])
        self.assertEqual(doc["packages"]["base-files"],
                         [{"version": "3.0.14-r0", "build": "base-files"}])

    def test_without_the_alternate_tree_its_entries_are_builds_of_their_own(self):
        doc, stats = self.build(alt=False)
        self.assertNotIn("kernel-module-foo-6.6.78", doc["packages"])
        self.assertIs(doc["builds"][self.alt]["packaged"], False)
        self.assertEqual(doc["counts"]["alternate_builds"], 2)
        self.assertEqual(stats.stale_dropped, 0)

    def test_an_alternate_with_nothing_listed_is_no_cve_record(self):
        scan = self.tree.manifest("quiet-alt", {"package": [
            entry("linux-raspberrypi", rt.DEFAULT_KERNEL, issue("CVE-2026-1")),
            entry(self.alt, rt.ALT_KERNEL),
        ]})
        doc, _ = build_report([scan], self.tree.dirs, status="All",
                              alt_trees=self.tree.alt_trees)
        self.assertEqual(binding_rules.build_verdict(doc, self.alt),
                         ("not_checked", "no-cve-record"))
        self.assertEqual(binding_rules.build_verdict(doc, "linux-raspberrypi"),
                         ("checked", {"CVE-2026-1": "affected"}))

    def test_the_default_listing_nothing_takes_no_other_record(self):
        scan = self.tree.manifest("quiet-default", {"package": [
            entry(self.alt, rt.ALT_KERNEL, issue("CVE-2026-3")),
        ]})
        doc, _ = build_report([scan], self.tree.dirs, status="All",
                              alt_trees=self.tree.alt_trees)
        self.assertEqual(binding_rules.build_verdict(doc, "linux-raspberrypi"),
                         ("not_checked", "build-unscanned"))
        self.assertEqual(binding_rules.build_verdict(doc, self.alt),
                         ("checked", {"CVE-2026-3": "affected"}))

    def test_an_alternate_entry_at_another_version_is_stale(self):
        scan = self.tree.manifest("stale", {"package": [
            entry(self.alt, rt.DEFAULT_KERNEL, issue("CVE-2026-3"))]})
        doc, stats = build_report([scan], self.tree.dirs, status="All",
                                  alt_trees=self.tree.alt_trees)
        self.assertEqual(stats.stale_dropped, 1)
        self.assertEqual(doc["builds"][self.alt]["coverage"], "unscanned")


class NoCveRecordTests(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        self.tree = rt.Tree(self.root)
        for recipe in ("avocadoctl", "glibc-locale", "zlib", "attr", "acl",
                       "busybox", "dbus", "cmocka", "twice"):
            self.tree.pkg("pkg-" + recipe, recipe, "1.0")

    def build(self, entries, status="All"):
        scan = self.tree.manifest("scan", {"package": entries})
        doc, stats = build_report([scan], self.tree.dirs, status=status)
        return doc, stats

    def entries(self):
        return [
            # A CPE no CVE record names, and none at all: both export an
            # empty issue list.
            entry("avocadoctl", "1.0"),
            entry("glibc-locale", "1.0"),
            entry("zlib", "1.0", issue("CVE-2026-1", "Patched", detail="fixed-version: 0.9")),
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

    def coverage(self, doc):
        return {bid: b["coverage"] for bid, b in doc["builds"].items()}

    def test_what_the_scanner_could_not_match_is_no_cve_record(self):
        doc, _ = self.build(self.entries())
        self.assertEqual(sorted(b for b, c in self.coverage(doc).items()
                                if c == "no-cve-record"), ["avocadoctl", "glibc-locale"])
        self.assertEqual(doc["counts"]["no_cve_record_builds"], 2)
        self.assertEqual(binding_rules.build_verdict(doc, "avocadoctl"),
                         ("not_checked", "no-cve-record"))

    def test_what_was_not_usably_scanned_is_unscanned_never_clean(self):
        doc, stats = self.build(self.entries())
        unscanned = sorted(b for b, c in self.coverage(doc).items() if c == "unscanned")
        self.assertEqual(unscanned, ["acl", "attr", "busybox", "cmocka", "dbus"])
        self.assertEqual(doc["counts"]["unscanned_builds"], 5)
        self.assertEqual((stats.stale_dropped, stats.entries_unreadable), (1, 2))
        for bid in unscanned:
            self.assertEqual(binding_rules.build_verdict(doc, bid),
                             ("not_checked", "build-unscanned"))

    def test_nothing_reads_as_clean_unless_it_was_scanned_clean(self):
        doc, _ = self.build(self.entries())
        for bid, build in doc["builds"].items():
            if build["coverage"] == "scanned":
                self.assertTrue(build["cves"], bid)

    def test_a_single_status_report_keeps_matched_builds_scanned(self):
        # zlib matched a CVE that this status leaves out: clean at Unpatched.
        doc, _ = self.build(self.entries(), status="Unpatched")
        self.assertEqual((doc["builds"]["zlib"]["coverage"], doc["builds"]["zlib"]["cves"]),
                         ("scanned", []))

    def test_an_unpackaged_entry_is_a_build_that_binds_nothing(self):
        doc, _ = self.build(self.entries() + [entry("gcc-cross", "1.0")])
        self.assertEqual((doc["builds"]["gcc-cross"]["packaged"],
                          doc["builds"]["gcc-cross"]["coverage"]), (False, "no-cve-record"))
        self.assertNotIn("version_keys", doc["builds"]["gcc-cross"])
        self.assertEqual(doc["counts"]["no_cve_record_builds"], 2)


class UpstreamWontfixTests(unittest.TestCase):
    """create-spdx writes a CVE_STATUS keyword as the VEX statement's status
    notes and sbom-cve-check exports those as "detail"; the report keeps it."""

    def test_the_detail_survives_both_paths_and_no_summary(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root)
        tree = rt.Tree(root)
        tree.pkg("shadow", "shadow", "4.19.4")
        scan = tree.manifest("scan", {"package": [entry(
            "shadow", "4.19.4",
            issue("CVE-2013-4235", "Ignored", detail="upstream-wontfix",
                  description="Severity is low and marked as closed and won't fix."),
            issue("CVE-2026-6", "Ignored", detail="cpe-incorrect"))]})
        for summary in (True, False):
            with self.subTest(summary=summary):
                doc, _ = build_report([scan], tree.dirs, status="All", summary=summary)
                again, _ = build_report_from_anchor([scan], round_trip(doc, root))
                for each in (doc, again):
                    cves = {c["id"]: c for c in each["builds"]["shadow"]["cves"]}
                    self.assertEqual(cves["CVE-2013-4235"]["detail"], "upstream-wontfix")
                    self.assertEqual(binding_rules.build_verdict(each, "shadow"),
                                     ("checked", {"CVE-2013-4235": "affected"}))


class NamesTests(unittest.TestCase):

    def test_a_build_id_is_the_label_the_feed_document_gives(self):
        self.assertEqual(report.build_id("jetson-rt", OOT), feedsbom.alt_label("jetson-rt", OOT))
        self.assertEqual(report.build_id("", OOT), OOT)
        for name in (OOT, "jetson-rt:" + OOT):
            self.assertEqual(report.build_id(*report.split_build_id(name)), name)
        self.assertEqual(report.split_build_id(":x"), ("", ":x"))

    def test_the_coverage_record_names_the_builds_left_out(self):
        record = {"alt_not_covered": [
            {"mc": "jetson-rt", "recipe": OOT, "reason": "VEX overlap: x"},
            {"mc": "", "recipe": "nocolon", "reason": "malformed entry"}]}
        self.assertEqual(report.not_covered_builds(record), {"jetson-rt:" + OOT: "VEX overlap: x"})
        for bad in ({}, {"alt_not_covered": {}}, {"alt_not_covered": ["x"]},
                    {"alt_not_covered": [{"mc": "a", "recipe": "b"}]}, []):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    report.not_covered_builds(bad)


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
        tree = rt.Tree(root)
        alt = tree.alt("rpi")
        recipes = {"linux-raspberrypi", "kernel-devsrc"}
        # Empty, then only a dependency the feed does not take from it.
        self.assertIn("no package of kernel-devsrc, linux-raspberrypi",
                      report.alt_tree_problem(alt, recipes))
        self.assertEqual(report.alt_tree_problem(alt, None),
                         "%s holds no readable package data" % alt)
        tree.pkg("base-files", "base-files", "3.0.14", mc="rpi")
        self.assertIn("no package of kernel-devsrc, linux-raspberrypi",
                      report.alt_tree_problem(alt, recipes))
        self.assertIsNone(report.alt_tree_problem(alt, None))
        tree.pkg("kernel-image-6.6.78", "linux-raspberrypi", rt.ALT_KERNEL, mc="rpi")
        self.assertIn("no package of kernel-devsrc", report.alt_tree_problem(alt, recipes))
        tree.pkg("kernel-devsrc-6.6.78", "kernel-devsrc", rt.ALT_KERNEL, mc="rpi")
        self.assertIsNone(report.alt_tree_problem(alt, recipes))
        self.assertIn("no runtime-reverse",
                      report.alt_tree_problem(os.path.join(root, "nowhere"), recipes))

    def test_an_alternate_tree_needs_its_multiconfig(self):
        with self.assertRaises(ValueError):
            report.read_trees([], [("", "/nowhere", None)], report.Stats())

    def test_alt_recipes_by_mc(self):
        pairs, _ = feedsbom.parse_alt_recipes("b:linux b:kernel-devsrc a:linux-l4t b:linux")
        self.assertEqual(list(feedsbom.alt_recipes_by_mc(pairs).items()),
                         [("b", {"linux", "kernel-devsrc"}), ("a", {"linux-l4t"})])


class SchemaTests(unittest.TestCase):
    """Every report the tests here build is valid against the version 2
    schema, and the schema refuses what the consumer refuses on shape."""

    def setUp(self):
        try:
            import jsonschema  # noqa: F401
        except ImportError:
            self.skipTest("jsonschema not installed")
        with open(SCHEMA) as f:
            self.schema = json.load(f)
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)

    def reports(self):
        jetson = JetsonTests("test_every_rpm_joins_its_own_build")
        jetson.setUp()
        self.addCleanup(jetson.doCleanups)
        yield jetson.build(not_covered={"jetson-rt:" + OOT: "why"})[0]
        tree = rt.Tree(self.root)
        scan = rt.one_tree(tree)
        for status in report.REPORT_STATUSES:
            for compiled in (None, {"linux-raspberrypi"}):
                yield build_report(rt.one_tree_rescan(tree) + [scan], tree.dirs, status=status,
                                   summary=status != "Patched", compiled_sources=compiled)[0]

    def test_the_reports_are_valid(self):
        import jsonschema
        for doc in self.reports():
            jsonschema.validate(round_trip(doc, self.root), self.schema)

    def test_the_schema_refuses_what_the_consumer_refuses(self):
        import jsonschema
        doc = round_trip(next(self.reports()), self.root)
        bid = "jetson-rt:" + OOT
        cases = [
            lambda d: d.update(version="1"),
            lambda d: d.pop("builds"),
            lambda d: d["builds"][bid].update(coverage="clean"),
            lambda d: d["builds"][bid].pop("not_covered") and d["builds"][bid].update(
                coverage="scanned"),
            lambda d: d["builds"][OOT].pop("cves"),
            lambda d: d["builds"][OOT].update(coverage="no-cve-record"),
            lambda d: d["packages"].update(kernel=[]),
            lambda d: d["packages"]["kernel"][0].pop("build"),
            lambda d: d.update(summary="yes"),
            lambda d: d["counts"].update(builds=-1),
            lambda d: d["builds"][OOT].pop("version_keys"),
        ]
        for n, mutate in enumerate(cases):
            with self.subTest(case=n):
                bad = json.loads(json.dumps(doc))
                mutate(bad)
                with self.assertRaises(jsonschema.ValidationError):
                    jsonschema.validate(bad, self.schema)


class CliTests(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        self.tree = rt.Tree(self.root)
        rt.rpi_kernels(self.tree)
        self.alt = self.tree.alts[rt.RPI_MC][0]
        self.scan = self.tree.manifest("feed", {"package": [
            entry("linux-raspberrypi", rt.DEFAULT_KERNEL, issue("CVE-2026-1")),
            entry("%s:linux-raspberrypi" % rt.RPI_MC, rt.ALT_KERNEL, issue("CVE-2026-3")),
        ]})

    def run_main(self, *argv):
        err = io.StringIO()
        with mock.patch.object(sys, "argv", ["report"] + list(argv)), \
                contextlib.redirect_stderr(err):
            try:
                rc = report.main()
            except SystemExit as e:
                rc = e.code
        return rc, err.getvalue()

    def test_the_cli_reads_an_alternate_tree_and_the_coverage_record(self):
        coverage = os.path.join(self.root, "coverage.json")
        with open(coverage, "w") as f:
            json.dump({"alt_not_covered": [{"mc": rt.RPI_MC, "recipe": "kernel-devsrc",
                                            "reason": "why"}]}, f)
        out = os.path.join(self.root, "out.json")
        rc, err = self.run_main(
            "--manifest", self.scan, "--pkgdata-dir", self.tree.machine,
            "--pkgdata-dir", self.tree.sdk,
            "--alt-pkgdata-dir", "%s:%s" % (rt.RPI_MC, self.alt),
            "--alt-recipe", "%s:linux-raspberrypi" % rt.RPI_MC,
            "--alt-recipe", "%s:kernel-devsrc" % rt.RPI_MC,
            "--coverage", coverage, "--status", "All", "-o", out)
        self.assertEqual(rc, 0, err)
        self.assertIn("alternate_builds: 2", err)
        self.assertIn("not_covered_builds: 1", err)
        with open(out) as f:
            doc = json.load(f)
        want, _ = build_report([self.scan], self.tree.dirs, status="All",
                               alt_trees=self.tree.alt_trees,
                               not_covered={"%s:kernel-devsrc" % rt.RPI_MC: "why"})
        doc["generated"] = want["generated"]
        self.assertEqual(doc, json.loads(json.dumps(want)))

    def test_the_cli_never_writes_over_the_coverage_record(self):
        coverage = os.path.join(self.root, "coverage.json")
        with open(coverage, "w") as f:
            json.dump({"alt_not_covered": []}, f)
        with open(coverage, "rb") as f:
            before = f.read()
        alias = os.path.join(self.root, "alias.json")
        os.link(coverage, alias)
        os.symlink(coverage, os.path.join(self.root, "linked.json.tmp"))
        for out in (coverage, alias, os.path.join(self.root, "linked.json"), self.scan):
            with self.subTest(out=out):
                rc, err = self.run_main(
                    "--manifest", self.scan, "--pkgdata-dir", self.tree.machine,
                    "--coverage", coverage, "-o", out)
                self.assertEqual(rc, 2)
                self.assertIn("one of the inputs", err)
        with open(coverage, "rb") as f:
            self.assertEqual(f.read(), before)
        self.assertTrue(os.path.exists(self.scan))

    def test_the_cli_refuses_malformed_alternate_arguments(self):
        out = os.path.join(self.root, "out.json")
        for extra, words in (
                (("--alt-pkgdata-dir", self.alt), "<multiconfig>:<value>"),
                (("--alt-pkgdata-dir", ":" + self.alt), "<multiconfig>:<value>"),
                (("--alt-recipe", "linux-raspberrypi"), "<multiconfig>:<value>"),
                (("--alt-recipe", "other:linux-raspberrypi"), "no --alt-pkgdata-dir"),
                (("--coverage", os.path.join(self.root, "nowhere.json")), "--coverage"),
                (("--alt-pkgdata-dir", "%s:%s" % (rt.RPI_MC, self.alt),
                  "--alt-recipe", "%s:linux-other" % rt.RPI_MC), "no package of linux-other"),
                (("--alt-pkgdata-dir", "e:" + os.path.join(self.root, "empty")),
                 "runtime-reverse")):
            with self.subTest(extra=extra):
                rc, err = self.run_main("--manifest", self.scan, "--pkgdata-dir",
                                        self.tree.machine, "--status", "All", "-o", out, *extra)
                self.assertEqual(rc, 2)
                self.assertIn(words, err)
                self.assertFalse(os.path.exists(out))


if __name__ == "__main__":
    unittest.main()
