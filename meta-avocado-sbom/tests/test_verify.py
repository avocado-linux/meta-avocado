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

from avocado_sbom import report, verify  # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "avocado-cve-report.json")

def load():
    with open(FIXTURE) as f:
        return json.load(f)

def load_patched():
    """The fixture as the Patched half of the same build. The fixture is the
    Unpatched one, so nothing else here sees a Patched status or an evidence.
    """
    doc = load()
    doc["status"] = "Patched"
    counts = doc["counts"]
    counts["unpatched_cves"], counts["patched_cves"] = (
        counts["patched_cves"], counts["unpatched_cves"])
    for recipe in doc["recipes"].values():
        for cve in recipe["cves"]:
            cve["evidence"] = "patch-file"
    return doc

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

    def test_the_patched_half_passes(self):
        patched = load_patched()
        self.assertEqual(verify.check_report(patched), [])
        self.assertEqual(verify.additions(patched), [])

    # Packages disappear, the counter does not notice.

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

    def test_scope_removed(self):
        # A producer that predates the scope field, or one that dropped it:
        # every finding then claims a surface it has not declared.
        for entry in self.report["recipes"].values():
            del entry["scope"]
        self.assertCaught(".scope")

    def test_scope_misspelled(self):
        # "runtime" reads plausible and means nothing. A free-string scope
        # would let a producer invent a fourth surface no consumer maps.
        next(iter(self.report["recipes"].values()))["scope"] = "runtime"
        self.assertCaught(".scope")

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

    def test_package_collisions_is_not_a_failure(self):
        # The first pkgdata directory wins, so the report is complete. The
        # recipe notes it; nothing here fails on it.
        self.report["counts"]["package_collisions"] = 3
        self.assertClean()

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

    def test_recipe_in_both_recipes_and_no_cve_record(self):
        # At a status other than "Unpatched" the generator once put a recipe
        # in both: cve-check writes cvesInRecord "No" for a product whose every
        # record it ignored or found patched, while the issues survive.
        name = next(iter(self.report["recipes"]))
        self.report["no_cve_record_recipes"].append(name)
        self.report["counts"]["no_cve_record_recipes"] += 1
        self.assertCaught("which recipes reports CVEs for")

    def test_recipe_in_both_recipes_and_unscanned(self):
        name = next(iter(self.report["recipes"]))
        self.report["unscanned_recipes"].append(name)
        self.report["counts"]["unscanned_recipes"] += 1
        self.assertCaught("which recipes reports CVEs for")

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
        # Contents change, envelope does not.
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
                    "scope": "feed",
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

class AltVersionsTests(unittest.TestCase):
    """A recipe the build produced at more than one version.

    An alt_versions record is held to the same standard as the entry: a record
    missing a scope is as broken as an entry missing one.
    """

    def setUp(self):
        self.report = load()
        self.entry = self.report["recipes"]["libpng"]
        self.entry["alt_versions"] = [{
            "version": "1.6.44",
            "packaged": True,
            "scope": "feed",
            "cves": [{"id": "CVE-2026-9999"}],
        }]
        self.report["counts"]["alt_recipes"] = 1
        self.report["counts"]["alt_cves"] = 1

    def assertCaught(self, substring):
        failures = verify.check_report(self.report)
        self.assertTrue(failures, "mutation was not caught")
        self.assertTrue(
            any(substring in f for f in failures),
            "no failure mentioned %r: %s" % (substring, failures),
        )

    def test_a_second_version_passes(self):
        self.assertEqual(verify.check_report(self.report), [])
        self.assertEqual(verify.additions(self.report), [])

    def test_the_alt_cves_are_not_counted_as_the_recipes_own(self):
        # Adding a version must not move "cves".
        self.assertEqual(
            self.report["counts"]["cves"],
            sum(len(e["cves"]) for e in self.report["recipes"].values()),
        )

    def test_alt_cves_dropped_silently(self):
        self.entry["alt_versions"][0]["cves"] = [{"id": "CVE-1"}, {"id": "CVE-2"}]
        self.assertCaught("counts.alt_cves")

    def test_a_recipe_gaining_a_version_without_the_counter(self):
        self.report["counts"]["alt_recipes"] = 0
        self.assertCaught("counts.alt_recipes")

    def test_a_record_with_no_scope_is_malformed(self):
        del self.entry["alt_versions"][0]["scope"]
        self.assertCaught("alt_versions[0].scope")

    def test_a_record_with_an_empty_cve_list_is_malformed(self):
        # Same rule as an entry: nothing to report means no record.
        self.entry["alt_versions"][0]["cves"] = []
        self.report["counts"]["alt_cves"] = 0
        self.assertCaught("alt_versions[0] has an empty cves list")

    def test_an_empty_alt_versions_list_is_malformed(self):
        self.entry["alt_versions"] = []
        self.report["counts"]["alt_recipes"] = 0
        self.report["counts"]["alt_cves"] = 0
        self.assertCaught("expected a non-empty list")

    def test_a_record_repeating_the_entrys_own_version_is_malformed(self):
        # Two records at one version would count its CVEs twice.
        self.entry["alt_versions"][0]["version"] = self.entry["version"]
        self.assertCaught("repeats version")

    def test_a_record_repeating_another_records_version_is_malformed(self):
        self.entry["alt_versions"].append(
            dict(self.entry["alt_versions"][0], cves=[{"id": "CVE-2026-8888"}])
        )
        self.report["counts"]["alt_cves"] = 2
        self.assertCaught("repeats version")

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

    def test_schema_statuses_match_the_generator(self):
        # The pair the unknown-status warning depends on: do_cve_report warns
        # when cve-check grows a status beyond CVE_STATUSES, but nothing tied
        # that list to the schema's enum, so the two could drift apart in
        # exactly the release the warning exists to survive.
        self.assertEqual(
            sorted(self.schema["properties"]["status"]["enum"]),
            sorted(verify.CVE_STATUSES),
        )

    def test_schema_evidence_matches_the_generator(self):
        # Same drift risk as the status enum: _evidence() picks from a tuple
        # the schema repeats by hand.
        from avocado_sbom.report import CVE_EVIDENCE

        self.assertEqual(
            sorted(
                self.schema["properties"]["recipes"]["additionalProperties"][
                    "properties"
                ]["cves"]["items"]["properties"]["evidence"]["enum"]
            ),
            sorted(CVE_EVIDENCE),
        )

    def test_schema_scopes_match_the_generator_and_the_checker(self):
        # Three declarations of one vocabulary: report.SCOPES, verify.SCOPES
        # (spelled out on purpose, so the checker does not take the producer's
        # word for it) and this enum. Nothing bound any pair of them.
        scopes = sorted(verify.SCOPES)
        self.assertEqual(
            sorted(
                self.schema["properties"]["recipes"]["additionalProperties"][
                    "properties"
                ]["scope"]["enum"]
            ),
            scopes,
        )
        self.assertEqual(sorted(report.SCOPES), scopes)

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

    def test_only_health_counters_are_documented_as_such(self):
        # The other direction, or a counter dropped from HEALTH_COUNTERS keeps
        # describing itself as one and the two disagree silently.
        properties = self.schema["properties"]["counts"]["properties"]
        for name, spec in properties.items():
            if spec["description"].startswith("Health."):
                self.assertIn(
                    name, verify.HEALTH_COUNTERS,
                    "the schema calls counts.%s a health counter but the "
                    "checker does not fail on it" % name,
                )

    def test_fixture_validates(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema not installed")
        jsonschema.validate(load(), self.schema)

    def test_the_patched_half_validates(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema not installed")
        jsonschema.validate(load_patched(), self.schema)

    def test_schema_rejects_a_report_missing_a_counter(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema not installed")
        report = load()
        del report["counts"]["package_collisions"]
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(report, self.schema)

    def alt_report(self):
        report = load()
        report["recipes"]["libpng"]["alt_versions"] = [{
            "version": "1.6.44",
            "packaged": True,
            "scope": "feed",
            "cves": [{"id": "CVE-2026-9999"}],
        }]
        report["counts"]["alt_recipes"] = 1
        report["counts"]["alt_cves"] = 1
        return report

    def test_schema_accepts_a_second_version(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema not installed")
        jsonschema.validate(self.alt_report(), self.schema)

    def test_schema_holds_a_second_version_to_the_entrys_own_shape(self):
        # alt_versions items refer to the entry schema rather than repeating
        # it. If that reference stops resolving, everything validates.
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema not installed")
        report = self.alt_report()
        del report["recipes"]["libpng"]["alt_versions"][0]["scope"]
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

class UnscannedDeclaredTests(unittest.TestCase):
    """The unscanned gate, after the declared count was replaced by declared
    reasons. The count could only say that the number moved, so the only way to
    answer it was to copy the new number back in; and one opt-out gained while
    one scan was lost left it silent. These assert the set instead.
    """

    def setUp(self):
        self.report = load()
        self.unscanned = list(self.report["unscanned_recipes"])
        # What the markers avocado-cve-optout writes would say for this build.
        self.declared = {n: "CVE_PRODUCT is empty" for n in self.unscanned}
        # Real recipes from the fixture's package set. Both lists are scoped to
        # recipes that shipped a package, and check_report enforces that, so a
        # made-up name would fail the envelope rather than this check.
        self.scanned = [
            r
            for r in sorted({p["recipe"] for p in self.report["packages"].values()})
            if r not in self.unscanned
        ]

    def _stops_being_scanned(self, name):
        self.report["unscanned_recipes"].append(name)
        self.report["counts"]["unscanned_recipes"] += 1

    def test_no_markers_means_no_check(self):
        # An older build tree has none; asserting against an empty map would
        # fail every unscanned recipe at once.
        self.assertEqual(verify.check_unscanned_declared(self.report, None), [])

    def test_every_unscanned_recipe_declared_passes(self):
        self.assertEqual(
            verify.check_unscanned_declared(self.report, self.declared), []
        )

    def test_the_fixture_is_not_held_to_a_build_figure(self):
        # The count check could never run against the fixture: 11 was
        # avocado-qemuarm64's number and the fixture carries its own. A set of
        # reasons is true on every machine, so the fixture can assert it.
        self.assertEqual(verify.check_report(self.report), [])
        self.assertEqual(
            verify.check_unscanned_declared(self.report, self.declared), []
        )

    def test_a_recipe_that_stopped_being_scanned_is_caught(self):
        victim = self.scanned[0]
        self._stops_being_scanned(victim)
        failures = verify.check_unscanned_declared(self.report, self.declared)
        self.assertTrue(failures)
        self.assertIn(victim, failures[0])

    def test_a_new_opt_out_does_not_fail_the_build(self):
        # The whole point. A packagegroup added today declares itself, and
        # nobody edits a number in a conf file to let the build through.
        newcomer = self.scanned[0]
        self._stops_being_scanned(newcomer)
        self.declared[newcomer] = "CVE_PRODUCT is empty"
        self.assertEqual(
            verify.check_unscanned_declared(self.report, self.declared), []
        )

    # Every mechanism avocado_cve_optout_reason() can report writes a marker,
    # so a recipe that hit one is declared and cannot reach this failure. The
    # reason strings are that function's, kept here as the tokens a reader
    # would be sent chasing.
    OPTOUT_MECHANISMS = (
        "CVE_PRODUCT",
        "CVE_CHECK_SKIP_RECIPE",
        "CVE_CHECK_LAYER_EXCLUDELIST",
        "CVE_CHECK_LAYER_INCLUDELIST",
    )

    def test_the_failure_names_no_cause_that_writes_a_marker(self):
        # A diagnostic that names one sends the reader after a cause that
        # cannot have produced what they are looking at: the same predicate
        # that would have caused it also declares the recipe, which is the one
        # thing that makes this check pass.
        self._stops_being_scanned(self.scanned[0])
        failures = verify.check_unscanned_declared(self.report, self.declared)
        self.assertTrue(failures)
        named = [m for m in self.OPTOUT_MECHANISMS if m in failures[0]]
        self.assertEqual(named, [])

    def test_an_accidental_opt_out_is_declared_like_a_deliberate_one(self):
        # The limit this check has, asserted so the docs cannot drift back to
        # claiming otherwise. A CVE_PRODUCT cleared by a bad rebase produces
        # the same marker as glibc-locale's deliberate deferral, so it is
        # declared and passes. Only a recipe with no marker at all fails.
        victim = self.scanned[0]
        self._stops_being_scanned(victim)
        accidental = {**self.declared, victim: "CVE_PRODUCT is empty"}
        self.assertEqual(
            verify.check_unscanned_declared(self.report, accidental), []
        )
        self.assertTrue(
            verify.check_unscanned_declared(self.report, self.declared)
        )

    def test_one_gained_and_one_lost_is_caught(self):
        # The failure a count structurally cannot see: the total does not move.
        newcomer, victim = self.scanned[0], self.scanned[1]
        self._stops_being_scanned(newcomer)
        self.declared[newcomer] = "CVE_PRODUCT is empty"
        self._stops_being_scanned(victim)
        failures = verify.check_unscanned_declared(self.report, self.declared)
        self.assertTrue(failures)
        self.assertIn(victim, failures[0])
        self.assertNotIn(newcomer, failures[0])

    def test_the_failure_names_every_undeclared_recipe(self):
        victims = self.scanned[:2]
        for name in victims:
            self._stops_being_scanned(name)
        failures = verify.check_unscanned_declared(self.report, self.declared)
        for name in victims:
            self.assertIn(name, failures[0])
        self.assertIn("2 recipe(s)", failures[0])

    def test_a_missing_list_is_left_to_the_envelope_check(self):
        # Absence is malformed, and check_report already fails on it. Two
        # failures for one defect reads as two defects.
        del self.report["unscanned_recipes"]
        self.assertEqual(
            verify.check_unscanned_declared(self.report, self.declared), []
        )
        self.assertTrue(verify.check_report(self.report, health=False))

    def test_a_non_report_does_not_raise(self):
        self.assertEqual(
            verify.check_unscanned_declared("not a report", {}), []
        )
        self.assertEqual(verify.check_unscanned_declared({}, {}), [])

    def test_it_stays_out_of_check_report_and_check_health(self):
        # The recipe calls it separately so it can carry its own message, and
        # because the markers are not in the report: a consumer holding only
        # the JSON cannot run this check at all.
        self._stops_being_scanned(self.scanned[0])
        self.assertEqual(verify.check_report(self.report), [])
        self.assertEqual(verify.check_health(self.report), [])
        self.assertTrue(
            verify.check_unscanned_declared(self.report, self.declared)
        )

class StaleOptoutTests(unittest.TestCase):
    """A marker that outlived its declaration silently widens what the check
    above lets through, so it is reported - but the recipe was scanned, so the
    report is complete and this does not fail a build.
    """

    def setUp(self):
        self.report = load()
        self.declared = {
            n: "CVE_PRODUCT is empty" for n in self.report["unscanned_recipes"]
        }
        self.shipped = sorted(
            {p["recipe"] for p in self.report["packages"].values()}
        )

    def test_markers_matching_the_build_are_quiet(self):
        self.assertEqual(
            verify.stale_optout_declarations(self.report, self.declared), []
        )

    def test_a_declared_recipe_that_was_scanned_is_reported(self):
        scanned = next(
            r for r in self.shipped if r not in self.report["unscanned_recipes"]
        )
        self.declared[scanned] = "CVE_PRODUCT is empty"
        failures = verify.stale_optout_declarations(self.report, self.declared)
        self.assertTrue(failures)
        self.assertIn(scanned, failures[0])

    def test_opt_outs_that_ship_nothing_are_not_stale(self):
        # A marker is written for every opt-out in the build - image recipes,
        # anything native - and almost none of them ship a package. Reporting
        # those would bury the one case that matters.
        self.declared["core-image-minimal"] = "CVE_PRODUCT is empty"
        self.declared["quilt-native"] = "CVE_PRODUCT is empty"
        self.assertEqual(
            verify.stale_optout_declarations(self.report, self.declared), []
        )

    def test_no_markers_means_no_check(self):
        self.assertEqual(
            verify.stale_optout_declarations(self.report, None), []
        )

    def test_a_non_report_does_not_raise(self):
        self.assertEqual(verify.stale_optout_declarations("not a report", {}), [])
        self.assertEqual(verify.stale_optout_declarations({}, {}), [])

class VersionTests(unittest.TestCase):
    def test_the_generator_major_is_supported(self):
        # Or the day REPORT_VERSION is bumped, every fresh report fails its
        # own check and takes the build with it.
        self.assertIn(verify.REPORT_VERSION, verify.SUPPORTED_MAJORS)

    def test_a_dotted_version_is_not_a_point_release(self):
        # "version" is the major, so "1.2" is not version 1 with something
        # added - it is a version the schema's const "1" rejects outright, and
        # reading it as "1" would accept a document no consumer agreed to.
        report = load()
        report["version"] = "1.2"
        self.assertTrue(verify.check_report(report, health=False))

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
