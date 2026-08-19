#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""Prove the report check by mutation.

Each test breaks the fixture the way a real regression would; the controls at
the end assert legitimate work still passes.

  python3 -m unittest discover -s meta-avocado-sbom/tests -p 'test_*.py'
"""

import copy
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

from avocado_sbom import verify  # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "avocado-cve-report.json")

def load():
    with open(FIXTURE) as f:
        return json.load(f)

class FixtureTests(unittest.TestCase):
    def setUp(self):
        self.report = load()

    def assertCaught(self, substring=None):
        failures = verify.check_report(self.report)
        self.assertTrue(failures, "mutation was not caught")
        if substring:
            self.assertTrue(
                any(substring in f for f in failures),
                "no failure mentioned %r: %s" % (substring, failures),
            )

    def assertClean(self):
        self.assertEqual(verify.check_report(self.report), [])

    def test_fixture_passes(self):
        self.assertClean()
        self.assertEqual(verify.additions(self.report), [])

    # ENG-2317: packages disappear, the counter does not notice.

    def test_packages_dropped_silently(self):
        for name in list(self.report["packages"])[:40]:
            del self.report["packages"][name]
        self.assertCaught("counts.packages")

    def test_packages_dropped_with_digest_updated(self):
        # Digest and count updated, packages still gone.
        for name in list(self.report["packages"])[:40]:
            del self.report["packages"][name]
        self.report["counts"]["packages"] = len(self.report["packages"])
        self.assertCaught("packages_digest")

    def test_package_set_swapped_under_a_stale_digest(self):
        pkg = next(iter(self.report["packages"]))
        self.report["packages"][pkg]["version"] = "0.0.0-r99"
        self.assertCaught("packages_digest")

    def test_packaged_cves_dropped(self):
        for entry in self.report["recipes"].values():
            if entry["packaged"]:
                entry["cves"] = entry["cves"][:1]
        self.assertCaught("counts.packaged_cves")

    def test_whole_recipe_dropped(self):
        name = next(iter(self.report["recipes"]))
        del self.report["recipes"][name]
        self.assertCaught("counts.recipes")

    def test_recipes_with_cves_but_nothing_packaged(self):
        # pkgdata never read: nothing correlates to an installed package.
        for entry in self.report["recipes"].values():
            entry["packaged"] = False
        self.report["counts"]["packaged_recipes"] = 0
        self.report["counts"]["packaged_cves"] = 0
        self.assertCaught("none of them correlated")

    def test_a_build_with_no_unpatched_cves_at_all_passes(self):
        # Must not read as a broken join.
        self.report["recipes"] = {}
        self.report["counts"].update(
            recipes=0, packaged_recipes=0, cves=0, packaged_cves=0
        )
        self.assertClean()

    def test_no_packages_at_all(self):
        self.report["packages"] = {}
        self.report["counts"]["packages"] = 0
        self.report["packages_digest"] = verify.packages_digest({})
        self.assertCaught("counts.packages is 0")

    def test_nothing_scanned(self):
        self.report["counts"]["cve_files"] = 0
        self.assertCaught("nothing was scanned")

    # Health counters.

    def test_package_collisions(self):
        self.report["counts"]["package_collisions"] = 3
        self.assertCaught("counts.package_collisions")

    def test_stale_dropped(self):
        self.report["counts"]["stale_dropped"] = 1
        self.assertCaught("counts.stale_dropped")

    def test_cve_files_unreadable(self):
        self.report["counts"]["cve_files_unreadable"] = 12
        self.assertCaught("counts.cve_files_unreadable")

    def test_pkgdata_unreadable(self):
        self.report["counts"]["pkgdata_unreadable"] = 1
        self.assertCaught("counts.pkgdata_unreadable")

    def test_health_counter_as_a_boolean(self):
        self.report["counts"]["stale_dropped"] = False
        self.assertCaught("expected an integer")

    def test_counts_block_removed(self):
        del self.report["counts"]
        self.assertCaught("missing top-level key 'counts'")

    def test_single_counter_removed(self):
        del self.report["counts"]["package_collisions"]
        self.assertCaught("counts is missing 'package_collisions'")

    def test_cve_record_without_an_id(self):
        entry = next(iter(self.report["recipes"].values()))
        del entry["cves"][0]["id"]
        self.assertCaught("CVE record with no id")

    def test_recipe_entry_reshaped(self):
        name = next(iter(self.report["recipes"]))
        self.report["recipes"][name] = ["CVE-2026-0001"]
        self.assertCaught("expected an object")

    def test_package_entry_missing_recipe(self):
        name = next(iter(self.report["packages"]))
        del self.report["packages"][name]["recipe"]
        self.assertCaught("no string recipe")

    def test_unknown_major_version(self):
        self.report["version"] = "2"
        self.assertCaught("this checker understands")

    def test_unknown_status(self):
        self.report["status"] = "Mitigated"
        self.assertCaught("not a cve-check status")

    def test_unscanned_list_and_counter_disagree(self):
        self.report["unscanned_recipes"] = []
        self.assertCaught("counts.unscanned_recipes")

    def test_no_cve_record_list_and_counter_disagree(self):
        self.report["no_cve_record_recipes"] = []
        self.assertCaught("counts.no_cve_record_recipes")

    def test_no_cve_record_list_removed(self):
        del self.report["no_cve_record_recipes"]
        self.assertCaught("missing top-level key 'no_cve_record_recipes'")

    def test_a_list_entry_that_is_not_a_string_is_reported_not_raised(self):
        # The checker's whole job is to report violations; a traceback out of
        # main() is a violation it failed to report.
        self.report["unscanned_recipes"] = [["glibc-locale"]]
        self.assertCaught("unscanned_recipes holds")

    def test_no_cve_record_list_holds_a_non_name(self):
        self.report["no_cve_record_recipes"].append("")
        self.assertCaught("no_cve_record_recipes holds")

    def test_a_recipe_in_both_lists(self):
        # The regression this counter exists to prevent: a recipe reported as
        # both examined and not examined.
        name = next(iter(self.report["packages"].values()))["recipe"]
        for key in ("unscanned_recipes", "no_cve_record_recipes"):
            if name not in self.report[key]:
                self.report[key].append(name)
                self.report["counts"][key] += 1
        self.assertCaught("both unscanned_recipes and no_cve_record_recipes")

    def test_no_cve_record_recipe_that_shipped_nothing(self):
        self.report["no_cve_record_recipes"].append("never-built")
        self.report["counts"]["no_cve_record_recipes"] += 1
        self.assertCaught("which shipped no package")

    def test_unscanned_recipe_that_shipped_nothing(self):
        self.report["unscanned_recipes"].append("never-built")
        self.report["counts"]["unscanned_recipes"] += 1
        self.assertCaught("which shipped no package")

    def test_optional_keys_may_be_absent(self):
        # A standalone run has neither.
        del self.report["machine"]
        del self.report["distro_version"]
        self.assertClean()

    def test_optional_key_of_the_wrong_type(self):
        self.report["machine"] = ["avocado-qemuarm64"]
        self.assertCaught("top-level 'machine'")

    def test_new_counter_is_an_addition_not_a_failure(self):
        self.report["counts"]["entries_unreadable"] = 0
        self.assertClean()
        self.assertEqual(verify.additions(self.report), ["counts.entries_unreadable"])

    def test_new_top_level_key_is_an_addition_not_a_failure(self):
        self.report["layers"] = {"meta-avocado": "abc123"}
        self.assertClean()
        self.assertEqual(verify.additions(self.report), ["top-level 'layers'"])

    # Controls. If these fail, the check is the problem.

    def test_ordinary_cve_churn_still_passes(self):
        entry = self.report["recipes"]["libxml2"]
        entry["cves"].append(
            {
                "id": "CVE-2026-99999",
                "link": "https://nvd.nist.gov/vuln/detail/CVE-2026-99999",
                "scorev3": "7.5",
                "summary": "A new advisory published after the fixture was cut.",
            }
        )
        self.report["counts"]["cves"] += 1
        self.report["counts"]["packaged_cves"] += 1
        self.assertClean()

    def test_a_mapping_correction_still_passes(self):
        # ENG-2196 shape: contents change, envelope does not.
        packages = self.report["packages"]
        name = next(iter(packages))
        packages[name] = dict(packages[name], recipe="libxml2", version="2.12.10-r0")
        self.report["packages_digest"] = verify.packages_digest(packages)
        self.assertClean()

    def test_a_rebuilt_report_with_entirely_different_contents_passes(self):
        # Nothing may depend on which packages or CVEs exist.
        packages = {
            "libfoo1": {"recipe": "foo", "version": "1.0-r0", "origin": "m"},
            "libbar1": {"recipe": "bar", "version": "2.0-r0", "origin": "m"},
            "libbaz1": {"recipe": "baz", "version": "3.0-r0", "origin": "m"},
        }
        report = {
            "version": "1",
            "generated": "2026-08-18T00:00:00Z",
            "status": "Unpatched",
            "packages_digest": verify.packages_digest(packages),
            "counts": dict.fromkeys(verify.REPORT_COUNTERS, 0),
            "recipes": {
                "foo": {
                    "version": "1.0",
                    "packaged": True,
                    "cves": [{"id": "CVE-2026-1"}],
                },
            },
            "packages": packages,
            "unscanned_recipes": ["bar"],
            "no_cve_record_recipes": ["baz"],
        }
        report["counts"].update(
            recipes=1, packages=3, packaged_recipes=1, cves=1, packaged_cves=1,
            unscanned_recipes=1, no_cve_record_recipes=1, cve_files=1,
        )
        self.assertEqual(verify.check_report(report), [])

SCHEMA = os.path.join(
    HERE, "..", "schema", "avocado-cve-report-v1.schema.json"
)

class SchemaTests(unittest.TestCase):
    """Schema and checker describe the same envelope; keep them in step."""

    def setUp(self):
        with open(SCHEMA) as f:
            self.schema = json.load(f)

    def test_schema_major_matches_the_generator(self):
        self.assertEqual(
            self.schema["properties"]["version"]["const"], verify.REPORT_VERSION
        )

    def test_required_top_level_keys_match_the_checker(self):
        self.assertEqual(
            sorted(self.schema["required"]), sorted(verify.TOP_LEVEL_TYPES)
        )

    def test_optional_top_level_keys_are_described(self):
        described = set(self.schema["properties"])
        self.assertEqual(
            described,
            set(verify.TOP_LEVEL_TYPES) | set(verify.OPTIONAL_TOP_LEVEL_TYPES),
        )

    def test_required_counters_match_the_checker(self):
        counts = self.schema["properties"]["counts"]
        self.assertEqual(
            sorted(counts["required"]), sorted(verify.REPORT_COUNTERS)
        )
        self.assertEqual(
            sorted(counts["properties"]), sorted(verify.REPORT_COUNTERS)
        )

    def test_health_counters_are_documented_as_such(self):
        properties = self.schema["properties"]["counts"]["properties"]
        for name in verify.HEALTH_COUNTERS:
            self.assertTrue(
                properties[name]["description"].startswith("Health."),
                "counts.%s is a health counter but the schema does not say so"
                % name,
            )

    def test_fixture_validates(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema not installed")
        jsonschema.validate(load(), self.schema)

    def test_schema_rejects_a_report_missing_a_counter(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema not installed")
        report = load()
        del report["counts"]["package_collisions"]
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(report, self.schema)

    def test_schema_accepts_an_added_counter(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema not installed")
        report = load()
        report["counts"]["entries_unreadable"] = 0
        jsonschema.validate(report, self.schema)

class SeverityTests(unittest.TestCase):
    """The split the recipe depends on: malformed always fails the build,
    incomplete is what AVOCADO_CVE_REPORT_STRICT governs.
    """

    def setUp(self):
        self.report = load()

    def test_a_lost_package_is_malformed_not_merely_incomplete(self):
        del self.report["packages"][next(iter(self.report["packages"]))]
        self.assertTrue(verify.check_report(self.report, health=False))

    def test_a_health_counter_is_incomplete_not_malformed(self):
        self.report["counts"]["stale_dropped"] = 4
        self.assertEqual(verify.check_report(self.report, health=False), [])
        self.assertTrue(verify.check_health(self.report))

    def test_a_missing_counter_is_malformed(self):
        del self.report["counts"]["stale_dropped"]
        self.assertTrue(verify.check_report(self.report, health=False))

    def test_check_report_is_the_union(self):
        self.report["counts"]["package_collisions"] = 2
        del self.report["counts"]["cve_files"]
        self.assertEqual(
            sorted(verify.check_report(self.report)),
            sorted(
                verify.check_report(self.report, health=False)
                + verify.check_health(self.report)
            ),
        )

    def test_health_of_a_non_report(self):
        self.assertEqual(verify.check_health("not a report"), [])

class ExpectedUnscannedTests(unittest.TestCase):
    """The declared band from ENG-2364. Opt-in on purpose: the fixture is a
    trimmed report and carries its own count, so a band asserted against the
    format rather than the configuration would fail a correct fixture.
    """

    def setUp(self):
        self.report = load()
        self.actual = self.report["counts"]["unscanned_recipes"]

    def test_no_declared_value_means_no_check(self):
        self.assertEqual(verify.check_expected_unscanned(self.report, None), [])

    def test_the_fixture_is_not_held_to_a_build_figure(self):
        # The whole reason the check is opt-in: 11 is avocado-qemuarm64's
        # number, the fixture legitimately carries a smaller one.
        self.assertEqual(verify.check_report(self.report), [])
        self.assertTrue(verify.check_expected_unscanned(self.report, 11))

    def test_the_declared_value_passes(self):
        self.assertEqual(
            verify.check_expected_unscanned(self.report, self.actual), []
        )

    def test_a_rise_is_caught(self):
        self.report["counts"]["unscanned_recipes"] = self.actual + 1
        failures = verify.check_expected_unscanned(self.report, self.actual)
        self.assertTrue(failures)
        self.assertIn("stopped being scanned", failures[0])

    def test_a_fall_is_caught_too(self):
        # A drop is not good news: an opt-out that became a scan, or a
        # declared value nobody has revisited.
        self.report["counts"]["unscanned_recipes"] = self.actual + 1
        failures = verify.check_expected_unscanned(self.report, self.actual + 2)
        self.assertTrue(failures)
        self.assertIn("stale", failures[0])

    def test_the_failure_names_the_recipes(self):
        self.report["counts"]["unscanned_recipes"] = self.actual + 1
        failures = verify.check_expected_unscanned(self.report, self.actual)
        for name in self.report["unscanned_recipes"]:
            self.assertIn(name, failures[0])

    def test_a_missing_counter_is_left_to_the_envelope_check(self):
        # Absence is malformed, and check_report already fails on it. Two
        # failures for one defect reads as two defects.
        del self.report["counts"]["unscanned_recipes"]
        self.assertEqual(verify.check_expected_unscanned(self.report, 11), [])
        self.assertTrue(verify.check_report(self.report, health=False))

    def test_a_non_report_does_not_raise(self):
        self.assertEqual(verify.check_expected_unscanned("not a report", 11), [])
        self.assertEqual(verify.check_expected_unscanned({}, 11), [])

    def test_it_stays_out_of_check_report_and_check_health(self):
        # The recipe calls it separately so it can carry its own message. The
        # count and its list move together, so this is a report that is valid
        # in every way except the value this configuration declared.
        self.report["unscanned_recipes"].pop()
        self.report["counts"]["unscanned_recipes"] = len(
            self.report["unscanned_recipes"]
        )
        self.assertEqual(verify.check_report(self.report), [])
        self.assertEqual(verify.check_health(self.report), [])
        self.assertTrue(
            verify.check_expected_unscanned(self.report, self.actual)
        )

class VersionTests(unittest.TestCase):
    def test_the_generator_major_is_supported(self):
        # Or the day REPORT_VERSION is bumped, every fresh report fails its
        # own check and takes the build with it.
        self.assertIn(
            verify.REPORT_VERSION.partition(".")[0], verify.SUPPORTED_MAJORS
        )

class CopyGuardTest(unittest.TestCase):
    """The tests mutate; make sure they mutate a copy, not the file."""

    def test_fixture_is_not_written_back(self):
        before = load()
        report = load()
        report["counts"]["packages"] = -1
        verify.check_report(report)
        self.assertEqual(before, load())
        self.assertIsNot(before, copy.deepcopy(before))

if __name__ == "__main__":
    unittest.main()
