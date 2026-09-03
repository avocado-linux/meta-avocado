# SPDX-License-Identifier: Apache-2.0

"""Check a CVE report against the frozen envelope.

Shape and derived counters only. Nothing here asserts on an expected set of
packages, recipes or CVEs: every check is the document against itself, or
against markers the same build produced. So a mapping correction never turns
CI red, even though a failure may name the recipes it found.
Run by CI against the fixture and by do_cve_report against every fresh report.
"""

import json

from avocado_sbom.report import CVE_STATUSES, REPORT_VERSION, packages_digest

# Must contain REPORT_VERSION's major, or a fresh report fails its own check.
SUPPORTED_MAJORS = ("1",)

# Present and numeric is frozen; the value is not.
REPORT_COUNTERS = (
    "recipes",
    "cves",
    "packaged_recipes",
    "packaged_cves",
    "packages",
    "cve_files",
    "stale_dropped",
    "unscanned_recipes",
    "no_cve_record_recipes",
    "cve_files_unreadable",
    "pkgdata_unreadable",
    "package_collisions",
    "unpatched_cves",
    "ignored_cves",
    "patched_cves",
    "unknown_status_cves",
    "manifests_read",
    "alt_recipes",
    "alt_cves",
)

# The surfaces a finding can occupy. Kept in step with report.SCOPES, but
# spelled out rather than imported: the checker is what a consumer runs against
# a document the producer wrote, so it must not take the producer's word for
# the vocabulary. test_verify.py binds this, report.SCOPES and the schema enum,
# so spelling it out cannot become drifting from it.
SCOPES = ("boot-chain", "base-runtime", "feed", "build-only")

# Non-zero means the report is missing data. Silent otherwise: the document
# stays schema-valid and the loss is just a number nobody reads.
#
# package_collisions is not one: the winner is the first pkgdata directory, so
# the report is complete and deterministic, just ambiguous about one name. The
# recipe notes it and the count stays in the document.
HEALTH_COUNTERS = (
    "stale_dropped",
    "cve_files_unreadable",
    "pkgdata_unreadable",
)

TOP_LEVEL_TYPES = {
    "version": str,
    "generated": str,
    "packages_digest": str,
    "status": str,
    "counts": dict,
    "recipes": dict,
    "packages": dict,
    "unscanned_recipes": list,
    "no_cve_record_recipes": list,
}

# Written by the recipe, not by build_report: a standalone run lacks both.
OPTIONAL_TOP_LEVEL_TYPES = {
    "machine": str,
    "distro_version": str,
}

def _is_int(value):
    # bool is an int subclass; a counter that is True rather than 1 is a bug.
    return isinstance(value, int) and not isinstance(value, bool)

def _check_envelope(report, fail):
    for key, want in TOP_LEVEL_TYPES.items():
        if key not in report:
            fail("missing top-level key %r" % key)
        elif not isinstance(report[key], want):
            fail(
                "top-level %r is %s, expected %s"
                % (key, type(report[key]).__name__, want.__name__)
            )

    for key, want in OPTIONAL_TOP_LEVEL_TYPES.items():
        if key in report and not isinstance(report[key], want):
            fail(
                "top-level %r is %s, expected %s"
                % (key, type(report[key]).__name__, want.__name__)
            )

    # Exact, not a major prefix: "version" *is* the major, so "1.2" is not a
    # point release this checker can read - it is a version the schema's
    # const "1" rejects outright.
    version = report.get("version")
    if isinstance(version, str) and version not in SUPPORTED_MAJORS:
        fail(
            "report version %r; this checker understands %s"
            % (version, ", ".join(SUPPORTED_MAJORS))
        )

    status = report.get("status")
    if isinstance(status, str) and status not in CVE_STATUSES:
        fail(
            "status %r is not a cve-check status (%s)"
            % (status, ", ".join(CVE_STATUSES))
        )

    generated = report.get("generated")
    if isinstance(generated, str) and not generated.endswith("Z"):
        fail("generated %r is not a UTC timestamp ending in Z" % generated)

    digest = report.get("packages_digest")
    if isinstance(digest, str) and not digest.startswith("sha256:"):
        fail("packages_digest %r is not sha256:-prefixed" % digest)

def _check_counts(report, fail):
    counts = report.get("counts")
    if not isinstance(counts, dict):
        return

    for name in REPORT_COUNTERS:
        if name not in counts:
            fail("counts is missing %r" % name)
        elif not _is_int(counts[name]):
            fail(
                "counts.%s is %s, expected an integer"
                % (name, type(counts[name]).__name__)
            )
        elif counts[name] < 0:
            fail("counts.%s is %d, expected a count" % (name, counts[name]))

def _check_record(label, entry, fail):
    """One recipe-at-a-version: a recipes entry, or an alt_versions record on
    one. Both carry the same four fields, so a consumer reads a version the
    same way wherever it found it.
    """
    if not isinstance(entry.get("version"), str):
        fail("%s has no string version" % label)
    if not isinstance(entry.get("packaged"), bool):
        fail("%s.packaged is not a boolean" % label)
    if entry.get("scope") not in SCOPES:
        fail("%s.scope is %r, expected one of %s"
             % (label, entry.get("scope"), ", ".join(SCOPES)))
    cves = entry.get("cves")
    if not isinstance(cves, list):
        fail("%s.cves is not a list" % label)
        return
    if not cves:
        fail("%s has an empty cves list; it should be absent" % label)
    for cve in cves:
        if not isinstance(cve, dict):
            fail("%s has a CVE record that is not an object" % label)
        elif not isinstance(cve.get("id"), str) or not cve["id"]:
            fail("%s has a CVE record with no id" % label)

def _check_entries(report, fail):
    recipes = report.get("recipes")
    if isinstance(recipes, dict):
        for name, entry in recipes.items():
            if not isinstance(entry, dict):
                fail("recipes[%r] is %s, expected an object"
                     % (name, type(entry).__name__))
                continue
            _check_record("recipes[%r]" % name, entry, fail)

            alt_versions = entry.get("alt_versions")
            if alt_versions is None:
                continue
            if not isinstance(alt_versions, list) or not alt_versions:
                fail("recipes[%r].alt_versions is %r, expected a non-empty "
                     "list; a recipe built at one version has no key"
                     % (name, alt_versions))
                continue
            # One record per version, the entry's own included: two at one
            # version would double-count its CVEs in alt_cves.
            seen = {entry.get("version")}
            for i, alt in enumerate(alt_versions):
                label = "recipes[%r].alt_versions[%d]" % (name, i)
                if not isinstance(alt, dict):
                    fail("%s is %s, expected an object"
                         % (label, type(alt).__name__))
                    continue
                _check_record(label, alt, fail)
                version = alt.get("version")
                if version in seen:
                    fail("%s repeats version %r, which the report already "
                         "carries for this recipe" % (label, version))
                seen.add(version)

    packages = report.get("packages")
    if isinstance(packages, dict):
        for name, entry in packages.items():
            if not isinstance(entry, dict):
                fail("packages[%r] is %s, expected an object"
                     % (name, type(entry).__name__))
                continue
            for field in ("recipe", "version", "origin"):
                if not isinstance(entry.get(field), str):
                    fail("packages[%r] has no string %s" % (name, field))
            if isinstance(entry.get("recipe"), str) and not entry["recipe"]:
                fail("packages[%r] has an empty recipe" % name)

    for key in ("unscanned_recipes", "no_cve_record_recipes"):
        names = report.get(key)
        if isinstance(names, list):
            for name in names:
                if not isinstance(name, str) or not name:
                    fail("%s holds %r, expected a recipe name" % (key, name))

def _check_derived(report, fail):
    counts = report.get("counts")
    recipes = report.get("recipes")
    packages = report.get("packages")
    unscanned = report.get("unscanned_recipes")
    no_record = report.get("no_cve_record_recipes")
    if not isinstance(counts, dict) or not isinstance(recipes, dict):
        return
    if not isinstance(packages, dict) or not isinstance(unscanned, list):
        return
    if not isinstance(no_record, list):
        return

    entries = [e for e in recipes.values() if isinstance(e, dict)]
    if len(entries) != len(recipes):
        # Shape errors are already reported; deriving from them adds noise.
        return

    packaged = [e for e in entries if e.get("packaged") is True]

    def cve_count(items):
        return sum(len(e["cves"]) for e in items if isinstance(e.get("cves"), list))

    # Kept out of "recipes", "cves" and "packaged_cves", so a consumer that
    # ignores alt_versions reads counters describing what it read.
    alt_records = [
        alt
        for e in entries
        for alt in (e.get("alt_versions") or ())
        if isinstance(alt, dict)
    ]

    derived = {
        "recipes": len(recipes),
        "packages": len(packages),
        "packaged_recipes": len(packaged),
        "cves": cve_count(entries),
        "packaged_cves": cve_count(packaged),
        "unscanned_recipes": len(unscanned),
        "no_cve_record_recipes": len(no_record),
        "alt_recipes": sum(1 for e in entries if e.get("alt_versions")),
        "alt_cves": cve_count(alt_records),
    }

    for name, want in derived.items():
        got = counts.get(name)
        if _is_int(got) and got != want:
            fail("counts.%s is %d, but the report holds %d" % (name, got, want))

    # The two lists partition the shipped recipes with the ones scanned and
    # found in the NVD, so a consumer can account for every shipped recipe
    # exactly once. That needs all three legs to be disjoint: overlap between
    # the lists would mean a recipe reported as both examined and not, and a
    # recipe in "recipes" is by definition not in either.
    shipped = {
        p["recipe"] for p in packages.values()
        if isinstance(p, dict) and isinstance(p.get("recipe"), str)
    }
    unscanned_names = {n for n in unscanned if isinstance(n, str)}
    no_record_names = {n for n in no_record if isinstance(n, str)}
    both = sorted(unscanned_names & no_record_names)
    if both:
        fail("%s in both unscanned_recipes and no_cve_record_recipes; a recipe "
             "nothing looked at cannot also have been looked up"
             % ", ".join(both[:5]))
    for key, names in (("unscanned_recipes", unscanned_names),
                       ("no_cve_record_recipes", no_record_names)):
        carried = sorted(names & set(recipes))
        if carried:
            fail("%s holds %s, which recipes reports CVEs for; the three are "
                 "one partition and a recipe is in exactly one"
                 % (key, ", ".join(carried[:5])))
    for key, names in (("unscanned_recipes", unscanned),
                       ("no_cve_record_recipes", no_record)):
        stray = sorted(n for n in names if isinstance(n, str) and n not in shipped)
        if stray:
            fail("%s holds %s, which shipped no package; both lists are scoped "
                 "to recipes in packages" % (key, ", ".join(stray[:5])))

    digest = report.get("packages_digest")
    if isinstance(digest, str) and all(
        isinstance(p, dict)
        and isinstance(p.get("recipe"), str)
        and isinstance(p.get("version"), str)
        for p in packages.values()
    ):
        want = packages_digest(packages)
        if digest != want:
            fail("packages_digest is %s, but the package set hashes to %s"
                 % (digest, want))

def _check_health(report, fail):
    """Well-formed but missing data. Separate because a build may be told to
    publish it anyway - see AVOCADO_CVE_REPORT_STRICT - but never a malformed
    one.
    """
    counts = report.get("counts")
    if not isinstance(counts, dict):
        return

    for name in HEALTH_COUNTERS:
        value = counts.get(name)
        if _is_int(value) and value != 0:
            fail(
                "counts.%s is %d; the report is missing data it should carry"
                % (name, value)
            )

    for name in ("packages", "cve_files"):
        value = counts.get(name)
        if _is_int(value) and value == 0:
            fail("counts.%s is 0; nothing was %s"
                 % (name, "packaged" if name == "packages" else "scanned"))

    # Only a failure when there were recipes to package: a build with no
    # unpatched CVEs correctly reports zero of everything.
    recipes = report.get("recipes")
    packaged_recipes = counts.get("packaged_recipes")
    if isinstance(recipes, dict) and recipes and packaged_recipes == 0:
        fail(
            "counts.packaged_recipes is 0 while %d recipe(s) carry CVEs; none "
            "of them correlated to an installed package, which is what a "
            "report built without pkgdata looks like" % len(recipes)
        )

def check_health(report):
    """Return the ways a well-formed report is missing data it should carry."""
    if not isinstance(report, dict):
        return []
    failures = []
    _check_health(report, failures.append)
    return failures

def _shipped_recipes(report):
    """The recipes that put at least one package in the image, from the report
    itself. build_report derives unscanned_recipes from this same set.
    """
    packages = report.get("packages")
    if not isinstance(packages, dict):
        return set()
    return {
        p["recipe"]
        for p in packages.values()
        if isinstance(p, dict) and isinstance(p.get("recipe"), str)
    }

def check_unscanned_declared(report, declared):
    """Return the recipes that shipped a package, have no cve-check result, and
    declare no reason for it.

    declared is the name -> reason map from report.read_optouts(), or None to
    skip the check - a tree built before avocado-cve-optout was inherited has
    no markers, and asserting against an empty map would fail every recipe.

    This is the check that replaced a declared count. A count could only ever
    say that the number moved, so the only way to answer it was to copy the
    new number back into the configuration; and a build that gained one opt-out
    while losing one scan left it silent. Naming the recipes makes both cases
    visible and neither of them a number anybody maintains.

    Out of check_report and check_health for the same reason the count was: the
    markers live beside the build's cve-check results, so a report checked on
    its own - the committed fixture, or one handed to a consumer - cannot
    produce them.
    """
    if declared is None or not isinstance(report, dict):
        return []

    unscanned = report.get("unscanned_recipes")
    if not isinstance(unscanned, list):
        return []

    undeclared = sorted(
        n for n in unscanned if isinstance(n, str) and n not in declared
    )
    if not undeclared:
        return []

    # Deliberately names no opt-out mechanism. Every predicate
    # avocado_cve_optout_reason() reports also writes a marker, so a recipe
    # that hit one is declared and never reaches this line; naming it would
    # send the reader after a cause that cannot have produced what they are
    # looking at. What is left is the scan not having run.
    return [
        "%d recipe(s) shipped a package, have no cve-check result and declare "
        "no reason for it: %s. Either the scan never ran for them - an "
        "interrupted build, avocado-cve-optout not inherited, a recipe still "
        "in pkgdata that this build's graph no longer reaches - or they opted "
        "out somewhere avocado-cve-optout does not look, in which case teach "
        "it that mechanism rather than widening what this accepts."
        % (len(undeclared), ", ".join(undeclared))
    ]

def stale_optout_declarations(report, declared):
    """Return the opt-outs that no longer describe the build: a recipe that
    declared one, shipped a package, and was scanned anyway.

    Not data loss - the recipe was scanned and its CVEs are in the report - so
    this is reported separately from check_unscanned_declared and does not fail
    a build. It means a marker outlived the declaration that produced it, which
    matters because a stale marker silently widens what the check above lets
    through.

    Restricted to recipes that shipped a package: a marker is written for every
    opt-out in the build, and most of them - image recipes, anything native -
    ship nothing and were never candidates for unscanned_recipes.
    """
    if declared is None or not isinstance(report, dict):
        return []

    unscanned = report.get("unscanned_recipes")
    if not isinstance(unscanned, list):
        return []

    scanned_anyway = sorted(
        (_shipped_recipes(report) & set(declared))
        - {n for n in unscanned if isinstance(n, str)}
    )
    if not scanned_anyway:
        return []

    return [
        "%d recipe(s) declare a cve-check opt-out but were scanned anyway: %s. "
        "The declaration is stale, or CVE_CHECK_DIR is carrying markers from a "
        "configuration this build no longer has."
        % (len(scanned_anyway), ", ".join(scanned_anyway))
    ]

def check_report(report, health=True):
    """Return the contract violations in a parsed report. health=False leaves
    out the data-loss checks.
    """
    failures = []
    if not isinstance(report, dict):
        return ["report is %s, expected an object" % type(report).__name__]

    _check_envelope(report, failures.append)
    _check_counts(report, failures.append)
    _check_entries(report, failures.append)
    _check_derived(report, failures.append)
    if health:
        _check_health(report, failures.append)
    return failures

def additions(report):
    """Keys this checker does not know about. Allowed without a major bump, so
    reported rather than failed on - but a typo also reads as an addition,
    while the counter it shadows goes missing.
    """
    found = []
    if not isinstance(report, dict):
        return found

    known = set(TOP_LEVEL_TYPES) | set(OPTIONAL_TOP_LEVEL_TYPES)
    found.extend("top-level %r" % k for k in sorted(set(report) - known))

    counts = report.get("counts")
    if isinstance(counts, dict):
        found.extend(
            "counts.%s" % k for k in sorted(set(counts) - set(REPORT_COUNTERS))
        )
    return found

def main():
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Check a CVE report against the frozen envelope"
    )
    parser.add_argument("report", nargs="+", help="report JSON to check")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="fail on unknown keys instead of reporting them",
    )
    parser.add_argument(
        "--optout-dir",
        metavar="DIR",
        help="CVE_CHECK_DIR holding *_optout.json markers; fail on any "
             "unscanned recipe that declares no reason for it",
    )
    args = parser.parse_args()

    declared = None
    if args.optout_dir is not None:
        from . import report as report_module

        declared, unreadable = report_module.read_optouts(args.optout_dir)
        if unreadable:
            print("%s: %d opt-out marker(s) could not be read"
                  % (args.optout_dir, unreadable), file=sys.stderr)
        if not declared:
            # Otherwise every unscanned recipe below is reported as undeclared,
            # which names the recipes but not the reason they all failed at
            # once. do_cve_report says this before it fails; so does this.
            print("%s: no *_optout.json markers here. Point --optout-dir at a "
                  "CVE_CHECK_DIR from a build that inherited "
                  "avocado-cve-optout." % args.optout_dir, file=sys.stderr)

    rc = 0
    for path in args.report:
        try:
            with open(path) as f:
                report = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print("%s: unreadable: %s" % (path, e), file=sys.stderr)
            rc = 1
            continue

        failures = check_report(report)
        failures.extend(check_unscanned_declared(report, declared))
        extra = additions(report)

        for message in failures:
            print("%s: %s" % (path, message), file=sys.stderr)
        for message in stale_optout_declarations(report, declared):
            print("%s: warning: %s" % (path, message), file=sys.stderr)
        for message in extra:
            print("%s: unknown key, not in version %s: %s"
                  % (path, REPORT_VERSION, message), file=sys.stderr)

        if failures or (extra and args.strict):
            rc = 1
            continue

        counts = report.get("counts", {})
        print(
            "%s: ok, version %s, %d packages, %d recipes, %d CVEs "
            "(%d recipes, %d CVEs packaged), health counters zero%s"
            % (
                path,
                report.get("version"),
                counts.get("packages", 0),
                counts.get("recipes", 0),
                counts.get("cves", 0),
                counts.get("packaged_recipes", 0),
                counts.get("packaged_cves", 0),
                # Silence would not distinguish a match from no declaration.
                "" if declared is None
                else ", every unscanned recipe declared",
            )
        )

    return rc

if __name__ == "__main__":
    raise SystemExit(main())
