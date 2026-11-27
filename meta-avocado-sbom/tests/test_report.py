#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""Prove what a build's version_keys carry and why a rescan needs them.

  python3 -m unittest discover -s meta-avocado-sbom/tests -p 'test_*.py'
"""

import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

import report_trees as rt  # noqa: E402
from avocado_sbom import report  # noqa: E402
from avocado_sbom.report import Stats, build_report, read_cve_data  # noqa: E402


def entry(name, version, *ids):
    return {
        "name": name,
        "version": version,
        "issue": [{"id": i, "status": "Unpatched"} for i in ids],
    }


def builds_of(doc):
    """The packaged builds of a report, as read_cve_data takes them."""
    return {bid: dict(recipe=b["recipe"], mc=b["mc"], keys=set(b["version_keys"]),
                      version=b["version"], packaged=True)
            for bid, b in doc["builds"].items() if b["packaged"]}


class VersionKeysTests(unittest.TestCase):
    """The defect: a rescan matched manifest entries against the packages'
    PKGV-PKGR, so a recipe whose PV is not that (glibc 2.43+git, a +git
    kernel) was dropped as stale, 76 CVEs against the build's 5,332.
    """

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        self.tree = rt.Tree(self.root)

    def populate(self):
        t = self.tree
        t.pkg("libc6", "glibc", "2.43+git", "2.43+git1+562cd7badd")
        t.pkg("glibc-utils", "glibc", "2.43+git", "2.43+git0+562cd7badd")
        t.pkg("libssl3", "openssl", "3.5.7")
        # Scanned clean: a build all the same, or a later scan's first CVE
        # for it reads as unpackaged.
        t.pkg("libz1", "zlib", "1.3.1")
        # No manifest entry at all this build; a later scan may have one.
        t.pkg("libattr1", "attr", "2.5.2")
        # A package with its own version writes only PKGV:<package>, which no
        # manifest entry carries, so it stays out of the keys.
        t.write("libdevmapper", "PN: lvm2\nPV: 2.03.39\nPKGV:libdevmapper: 1.02.213\n"
                "PKGR:libdevmapper: r0.3\n")
        self.manifest = t.manifest("world", {"package": [
            entry("glibc", "2.43+git", "CVE-2026-1"),
            entry("openssl", "3.5.7", "CVE-2026-2"),
            entry("zlib", "1.3.1"),
        ]})

    def build(self):
        return build_report([self.manifest], self.tree.dirs)[0]

    def test_every_pkgdata_version_is_listed_sorted(self):
        self.populate()
        doc = self.build()
        self.assertEqual({b: v["version_keys"] for b, v in doc["builds"].items()}, {
            "attr": ["2.5.2"],
            "glibc": ["2.43+git", "2.43+git0+562cd7badd", "2.43+git1+562cd7badd"],
            "lvm2": ["2.03.39"],
            "openssl": ["3.5.7"],
            "zlib": ["1.3.1"],
        })
        self.assertEqual(doc["builds"]["attr"]["coverage"], "unscanned")
        self.assertEqual(doc["builds"]["zlib"]["coverage"], "no-cve-record")
        self.assertEqual(doc["builds"]["glibc"]["version"], "2.43+git")
        self.assertEqual(doc["packages"]["libdevmapper"],
                         [{"version": "1.02.213-r0.3", "build": "lvm2"}])

    def test_the_document_is_deterministic(self):
        self.populate()
        first, second = self.build(), self.build()
        for doc in (first, second):
            del doc["generated"]
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))

    def test_a_rescan_from_the_keys_keeps_what_the_build_kept(self):
        self.populate()
        doc = self.build()

        from_keys = Stats()
        records, _ = read_cve_data([self.manifest], builds_of(doc), from_keys)
        self.assertEqual(set(records), {b for b, v in doc["builds"].items() if v.get("cves")})
        self.assertEqual(from_keys.stale_dropped, 0)

        # The control: the packages' own versions lose glibc.
        from_packages = Stats()
        builds = builds_of(doc)
        for b in builds.values():
            b["keys"] = set()
        for entries in doc["packages"].values():
            for e in entries:
                builds[e["build"]]["keys"].add(e["version"])
        records, _ = read_cve_data([self.manifest], builds, from_packages)
        self.assertNotIn("glibc", records)
        self.assertGreater(from_packages.stale_dropped, 0)

    def test_a_package_name_two_directories_claim_keeps_both_builds(self):
        # The first pkgdata directory wins the name, but the loser's recipe
        # still matched its entry at build time, so it is a build too.
        self.populate()
        self.tree.pkg("libssl3", "openssl-vendor", "1.1.1w", sdk=True)
        with open(self.manifest) as f:
            data = json.load(f)
        # Clean at build time.
        data["package"].append(entry("openssl-vendor", "1.1.1w"))
        with open(self.manifest, "w") as f:
            json.dump(data, f)

        doc = self.build()
        self.assertEqual(doc["packages"]["libssl3"], [{"version": "3.5.7-r0", "build": "openssl"}])
        self.assertEqual(doc["builds"]["openssl-vendor"]["version_keys"], ["1.1.1w"])
        self.assertEqual(doc["builds"]["openssl-vendor"]["coverage"], "no-cve-record")
        self.assertEqual(doc["counts"]["package_collisions"], 1)

        # Its first CVE, in a later scan.
        data["package"][-1] = entry("openssl-vendor", "1.1.1w", "CVE-2026-3")
        with open(self.manifest, "w") as f:
            json.dump(data, f)
        builds = builds_of(doc)
        records, _ = read_cve_data([self.manifest], builds, Stats())
        self.assertIn("openssl-vendor", records)
        self.assertIs(builds["openssl-vendor"]["packaged"], True)

    def test_a_rescan_drops_a_stale_entry_for_a_build_never_scanned(self):
        self.populate()
        doc = self.build()
        with open(self.manifest, "w") as f:
            json.dump({"package": [entry("attr", "2.5.1", "CVE-2026-4")]}, f)
        stats = Stats()
        records, _ = read_cve_data([self.manifest], builds_of(doc), stats)
        self.assertNotIn("attr", records)
        self.assertEqual(stats.stale_dropped, 1)

    def test_packages_digest_does_not_cover_them(self):
        self.populate()
        doc = self.build()
        digest = hashlib.sha256()
        for name in sorted(doc["packages"]):
            for e in doc["packages"][name]:
                digest.update(("%s\t%s\t%s\n" % (name, e["build"], e["version"])).encode())
        self.assertEqual(doc["packages_digest"], "sha256:" + digest.hexdigest())


class DigestTests(unittest.TestCase):

    def test_an_alternate_line_carries_its_multiconfig(self):
        packages = {"kernel": [{"version": "6.6-r0", "build": "rpi:linux"},
                               {"version": "6.12-r0", "build": "linux"}],
                    "a": [{"version": "1-r0", "build": "x"}]}
        lines = b"a\tx\t1-r0\nkernel\tlinux\t6.12-r0\nkernel\tlinux\t6.6-r0\trpi\n"
        self.assertEqual(report.packages_digest(packages),
                         "sha256:" + hashlib.sha256(lines).hexdigest())

    def test_the_order_of_the_lists_does_not_matter(self):
        packages = {"kernel": [{"version": "6.6-r0", "build": "rpi:linux"},
                               {"version": "6.12-r0", "build": "linux"}]}
        flipped = {"kernel": list(reversed(packages["kernel"]))}
        self.assertEqual(report.packages_digest(packages), report.packages_digest(flipped))


class AltMergeOrderTests(unittest.TestCase):
    PAIRS = [("mc-a", "linux"), ("mc-b", "foo"), ("mc-a", "foo"), ("mc-b", "linux")]

    def test_pair_by_pair_by_default(self):
        self.assertEqual(report.alt_merge_order(self.PAIRS),
                         ["mc-a:linux", "mc-b:foo", "mc-a:foo", "mc-b:linux"])

    def test_by_multiconfig_ranks_a_whole_tree_at_its_first_pair(self):
        # mc-a's foo is published with mc-a's tree, before mc-b's.
        self.assertEqual(report.alt_merge_order(self.PAIRS, by_multiconfig=True),
                         ["mc-a:linux", "mc-a:foo", "mc-b:foo", "mc-b:linux"])

    def test_the_cli_option_reaches_the_order(self):
        parsed = []
        real = report.alt_merge_order

        def spy(pairs, by_multiconfig=False):
            parsed.append(by_multiconfig)
            return real(pairs, by_multiconfig)

        report.alt_merge_order = spy
        argv = sys.argv
        try:
            with tempfile.TemporaryDirectory() as tmp:
                with open(os.path.join(tmp, "m" + report.MANIFEST_SUFFIX), "w") as f:
                    json.dump({"version": "1", "package": []}, f)
                for flag in ([], ["--merge-by-multiconfig"]):
                    sys.argv = (["report.py", "--manifest", tmp, "--pkgdata-dir", tmp,
                                 "--alt-pkgdata-dir", "mc-a:" + tmp,
                                 "--alt-recipe", "mc-a:linux"] + flag
                                + ["-o", os.path.join(tmp, "out.json")])
                    with self.assertRaises(SystemExit):
                        report.main()
        finally:
            report.alt_merge_order = real
            sys.argv = argv
        self.assertEqual(parsed, [False, True])


if __name__ == "__main__":
    unittest.main()
