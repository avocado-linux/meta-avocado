#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""One report listing every CVE status, each CVE carrying its own.

A report that lists one status only counts the rest, so a fix shows up as a
finding disappearing between two builds and a consumer cannot tell a CVE that
was patched from one that was ignored or never scanned. A consumer that
rejects single-status reports needs the whole picture in one document.

  python3 -m unittest discover -s meta-avocado-sbom/tests -p 'test_*.py'
"""

import copy
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

from avocado_sbom import report, verify  # noqa: E402
from avocado_sbom.report import (  # noqa: E402
    Stats,
    build_report,
    filtered_counts,
    obsolete_paths,
    parse_statuses,
    read_cve_data,
    status_paths,
)

SCHEMA = os.path.join(HERE, "..", "schema", "avocado-cve-report-v1.schema.json")

def entry(name, version="1.0", issues=()):
    return {
        "name": name,
        "version": version,
        "products": [{"product": name, "cvesInRecord": "Yes"}],
        "issue": list(issues),
    }

def issue(cve, status, **extra):
    return dict({"id": cve, "status": status}, **extra)

class Tree(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="avocado-status-all-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.cve_dir = os.path.join(self.tmp, "cve")
        self.pkgdata = os.path.join(self.tmp, "pkgdata")
        os.makedirs(self.cve_dir)
        os.makedirs(os.path.join(self.pkgdata, "runtime-reverse"))

    def write_cve(self, recipe, *entries):
        with open(os.path.join(self.cve_dir, "%s_cve.json" % recipe), "w") as f:
            json.dump({"package": list(entries)}, f)

    def write_pkg(self, name, recipe=None, version="1.0", release="r0.1"):
        with open(os.path.join(self.pkgdata, "runtime-reverse", name), "w") as f:
            f.write("PN: %s\nPV: %s\nPKGV: %s\nPKGR: %s\n"
                    % (recipe or name, version, version, release))

    def build(self, status, **kw):
        return build_report(self.cve_dir, [self.pkgdata], machine="m",
                            status=status, **kw)

class ListedTests(Tree):
    def setUp(self):
        super().setUp()
        self.write_pkg("openssl")
        self.write_cve("openssl", entry("openssl", issues=[
            issue("CVE-1", "Unpatched"),
            issue("CVE-2", "Patched"),
            issue("CVE-3", "Ignored", detail="cpe-incorrect"),
        ]))

    def cves(self, status, **kw):
        doc, _ = self.build(status, **kw)
        return {c["id"]: c for c in doc["recipes"]["openssl"]["cves"]}

    def test_every_status_is_listed(self):
        self.assertEqual(sorted(self.cves("All")), ["CVE-1", "CVE-2", "CVE-3"])

    def test_each_cve_carries_its_own_status(self):
        got = self.cves("All")
        self.assertEqual({k: v["status"] for k, v in got.items()},
                         {"CVE-1": "Unpatched", "CVE-2": "Patched", "CVE-3": "Ignored"})

    def test_the_documents_own_status_is_all(self):
        self.assertEqual(self.build("All")[0]["status"], "All")

    def test_a_single_status_document_is_unchanged(self):
        got = self.cves("Unpatched")
        self.assertEqual(list(got), ["CVE-1"])
        self.assertNotIn("status", got["CVE-1"])

    def test_the_evidence_follows_each_cves_own_status(self):
        got = self.cves("All")
        self.assertNotIn("evidence", got["CVE-1"])
        self.assertEqual(got["CVE-2"]["evidence"], "cve-check")
        self.assertEqual(got["CVE-3"]["evidence"], "cve-status")

    def test_a_backport_marker_promotes_only_a_patched_cve(self):
        got = self.cves("All", backports={"openssl": {"CVE-1", "CVE-2"}})
        self.assertNotIn("evidence", got["CVE-1"])
        self.assertEqual(got["CVE-2"]["evidence"], "patch-file")

    def test_dropping_the_prose_keeps_the_status(self):
        self.write_cve("openssl", entry("openssl", issues=[
            issue("CVE-1", "Patched", summary="s", description="d")]))
        got = self.cves("All", summary=False)
        self.assertEqual(got["CVE-1"]["status"], "Patched")
        self.assertNotIn("summary", got["CVE-1"])

    def test_a_status_cve_check_never_emits_is_still_unlisted_and_counted(self):
        self.write_cve("openssl", entry("openssl", issues=[
            issue("CVE-1", "Unpatched"), issue("CVE-9", "Mystery")]))
        doc, _ = self.build("All")
        self.assertEqual([c["id"] for c in doc["recipes"]["openssl"]["cves"]],
                         ["CVE-1"])
        self.assertEqual(doc["counts"]["unknown_status_cves"], 1)

class CountersTests(Tree):
    """At a single status the three per-status counters name what was left out.
    At All nothing is left out, so they name what is listed.
    """

    def test_they_count_what_is_listed(self):
        self.write_pkg("openssl")
        self.write_cve("openssl", entry("openssl", issues=[
            issue("CVE-1", "Unpatched"), issue("CVE-2", "Patched"),
            issue("CVE-3", "Patched"), issue("CVE-4", "Ignored")]))
        counts = self.build("All")[0]["counts"]
        self.assertEqual((counts["unpatched_cves"], counts["patched_cves"],
                          counts["ignored_cves"]), (1, 2, 1))
        self.assertEqual(counts["cves"], 4)

    def test_at_one_status_they_still_count_what_was_left_out(self):
        self.write_pkg("openssl")
        self.write_cve("openssl", entry("openssl", issues=[
            issue("CVE-1", "Unpatched"), issue("CVE-2", "Patched")]))
        counts = self.build("Unpatched")[0]["counts"]
        self.assertEqual((counts["unpatched_cves"], counts["patched_cves"]), (0, 1))

    def test_a_repeated_id_is_counted_once(self):
        # Two entries for one recipe name one CVE twice; the document holds it
        # once, so the counter must too or a report disagrees with itself.
        self.write_pkg("openssl")
        self.write_cve("openssl",
                       entry("openssl", issues=[issue("CVE-1", "Patched")]),
                       entry("openssl", issues=[issue("CVE-1", "Patched"),
                                                issue("CVE-2", "Patched")]))
        doc, _ = self.build("All")
        self.assertEqual(doc["counts"]["patched_cves"], 2)
        self.assertEqual(doc["counts"]["cves"], 2)

    def test_an_alternate_versions_cves_are_counted_by_status(self):
        alt_dir = os.path.join(self.cve_dir, "mc")
        os.makedirs(alt_dir)
        alt_pkgdata = os.path.join(self.tmp, "alt-pkgdata")
        os.makedirs(os.path.join(alt_pkgdata, "runtime-reverse"))
        with open(os.path.join(alt_pkgdata, "runtime-reverse", "kernel"), "w") as f:
            f.write("PN: linux\nPV: 6.6\nPKGV: 6.6\nPKGR: r0.1\n")
        self.write_pkg("kernel", recipe="linux", version="6.12")
        self.write_cve("linux", entry("linux", version="6.12",
                                      issues=[issue("CVE-1", "Unpatched")]))
        with open(os.path.join(alt_dir, "linux_cve.json"), "w") as f:
            json.dump({"package": [entry("linux", version="6.6", issues=[
                issue("CVE-2", "Patched"), issue("CVE-3", "Ignored")])]}, f)
        doc, _ = build_report(self.cve_dir, [self.pkgdata, alt_pkgdata],
                              machine="m", status="All", alt_cve_dirs=[alt_dir])
        counts = doc["counts"]
        self.assertEqual((counts["unpatched_cves"], counts["patched_cves"],
                          counts["ignored_cves"]), (1, 1, 1))
        self.assertEqual(counts["alt_cves"], 2)

class StatusVocabularyTests(unittest.TestCase):
    def test_all_is_a_status_a_document_may_ask_for(self):
        self.assertEqual(parse_statuses("All"), ["All"])

    def test_all_can_sit_beside_a_single_status(self):
        self.assertEqual(parse_statuses("All Unpatched"), ["All", "Unpatched"])

    def test_an_unknown_status_is_still_refused_and_all_is_offered(self):
        with self.assertRaises(ValueError) as caught:
            parse_statuses("Bogus")
        self.assertIn("All", str(caught.exception))

    def test_build_report_refuses_an_unknown_status(self):
        with self.assertRaises(ValueError) as caught:
            build_report("/nonexistent", [], status="Bogus")
        self.assertIn("All", str(caught.exception))

    def test_cve_statuses_is_still_what_cve_check_emits(self):
        # Filtering on All as though cve-check emitted it would match no issue.
        self.assertNotIn("All", report.CVE_STATUSES)
        self.assertEqual(report.REPORT_STATUSES, report.CVE_STATUSES + ("All",))

    def test_all_keeps_the_path_when_first(self):
        self.assertEqual(status_paths("/d/r.json", ["All"]), {"All": "/d/r.json"})

    def test_all_beside_another_status_is_suffixed(self):
        self.assertEqual(status_paths("/d/r.json", ["Unpatched", "All"]),
                         {"Unpatched": "/d/r.json", "All": "/d/r-all.json"})

    def test_a_leftover_all_document_is_obsolete_when_not_asked_for(self):
        out = status_paths("/d/r.json", ["Unpatched"])
        self.assertIn("/d/r-all.json", obsolete_paths("/d/r.json", out))

    def test_the_default_statuses_do_not_include_all(self):
        # Asking for All is a deliberate choice for a consumer that wants it;
        # the unsuffixed file existing consumers fetch keeps what it held.
        self.assertNotIn("All", report.DEFAULT_STATUSES)

class FilteredCountsTests(unittest.TestCase):
    COUNTS = {"unpatched_cves": 3, "patched_cves": 5, "ignored_cves": 1,
              "unknown_status_cves": 2}

    def test_at_all_only_unknown_statuses_are_left_out(self):
        self.assertEqual(filtered_counts(self.COUNTS, status="All"),
                         "2 unknown status")

    def test_at_all_with_nothing_unknown_is_empty(self):
        counts = dict(self.COUNTS, unknown_status_cves=0)
        self.assertEqual(filtered_counts(counts, status="All"), "")

    def test_without_a_status_the_old_behaviour_stands(self):
        self.assertEqual(filtered_counts(self.COUNTS),
                         "3 unpatched, 5 patched, 1 ignored, 2 unknown status")

class VerifyTests(Tree):
    def setUp(self):
        super().setUp()
        self.write_pkg("openssl")
        self.write_cve("openssl", entry("openssl", issues=[
            issue("CVE-1", "Unpatched"), issue("CVE-2", "Patched"),
            issue("CVE-3", "Ignored")]))
        self.doc = self.build("All")[0]
        for recipe in self.doc["recipes"].values():
            recipe["scope"] = "base-runtime"

    def caught(self, substring):
        failures = verify.check_report(self.doc, health=False)
        self.assertTrue(any(substring in f for f in failures),
                        "not caught (%r): %s" % (substring, failures))

    def test_an_all_report_passes(self):
        self.assertEqual(verify.check_report(self.doc, health=False), [])

    def test_a_cve_without_a_status_is_caught(self):
        del self.doc["recipes"]["openssl"]["cves"][0]["status"]
        self.caught("status")

    def test_a_cve_with_a_status_cve_check_never_emits_is_caught(self):
        self.doc["recipes"]["openssl"]["cves"][0]["status"] = "All"
        self.caught("status")

    def test_a_per_status_counter_that_disagrees_is_caught(self):
        self.doc["counts"]["patched_cves"] += 1
        self.caught("patched_cves")

    def test_every_per_status_counter_is_checked(self):
        for name in ("unpatched_cves", "patched_cves", "ignored_cves"):
            doc = copy.deepcopy(self.doc)
            doc["counts"][name] += 1
            failures = verify.check_report(doc, health=False)
            self.assertTrue(any(name in f for f in failures), name)

    def test_a_single_status_report_may_have_leftover_counters(self):
        # At one status those counters name what was left out, which no
        # document can be checked against.
        doc = self.build("Unpatched")[0]
        for recipe in doc["recipes"].values():
            recipe["scope"] = "base-runtime"
        doc["counts"]["patched_cves"] = 99
        self.assertEqual(verify.check_report(doc, health=False), [])

class SchemaTests(Tree):
    def setUp(self):
        super().setUp()
        try:
            import jsonschema  # noqa: F401
        except ImportError:
            self.skipTest("jsonschema not installed")
        with open(SCHEMA) as f:
            self.schema = json.load(f)
        self.write_pkg("openssl")
        self.write_cve("openssl", entry("openssl", issues=[
            issue("CVE-1", "Unpatched"), issue("CVE-2", "Patched")]))
        self.doc = self.build("All")[0]
        for recipe in self.doc["recipes"].values():
            recipe["scope"] = "base-runtime"

    def test_an_all_report_validates(self):
        import jsonschema
        jsonschema.validate(self.doc, self.schema)

    def test_the_status_enum_is_the_vocabulary_the_generator_accepts(self):
        self.assertEqual(self.schema["properties"]["status"]["enum"],
                         list(report.REPORT_STATUSES))

    def test_a_cve_status_outside_the_vocabulary_is_refused(self):
        import jsonschema
        self.doc["recipes"]["openssl"]["cves"][0]["status"] = "Mystery"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(self.doc, self.schema)

if __name__ == "__main__":
    unittest.main()
