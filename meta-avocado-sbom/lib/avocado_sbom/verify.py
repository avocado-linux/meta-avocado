# SPDX-License-Identifier: Apache-2.0

"""Check a CVE report against the frozen envelope.

Shape and derived counters only. Nothing here asserts on which packages,
recipes or CVEs a report carries, so a mapping correction never turns CI red.
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
    "cve_files_unreadable",
    "pkgdata_unreadable",
    "package_collisions",
    "unpatched_cves",
    "ignored_cves",
    "patched_cves",
    "unknown_status_cves",
)

# Non-zero means the report is missing data. Silent otherwise: the document
# stays schema-valid and the loss is just a number nobody reads.
HEALTH_COUNTERS = (
    "stale_dropped",
    "cve_files_unreadable",
    "pkgdata_unreadable",
    "package_collisions",
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

    version = report.get("version")
    if isinstance(version, str):
        major = version.partition(".")[0]
        if major not in SUPPORTED_MAJORS:
            fail(
                "report version %r has major %r; this checker understands %s"
                % (version, major, ", ".join(SUPPORTED_MAJORS))
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


def _check_entries(report, fail):
    recipes = report.get("recipes")
    if isinstance(recipes, dict):
        for name, entry in recipes.items():
            if not isinstance(entry, dict):
                fail("recipes[%r] is %s, expected an object"
                     % (name, type(entry).__name__))
                continue
            if not isinstance(entry.get("version"), str):
                fail("recipes[%r] has no string version" % name)
            if not isinstance(entry.get("packaged"), bool):
                fail("recipes[%r].packaged is not a boolean" % name)
            cves = entry.get("cves")
            if not isinstance(cves, list):
                fail("recipes[%r].cves is not a list" % name)
                continue
            if not cves:
                fail("recipes[%r] has an empty cves list; it should be absent"
                     % name)
            for cve in cves:
                if not isinstance(cve, dict):
                    fail("recipes[%r] has a CVE record that is not an object"
                         % name)
                elif not isinstance(cve.get("id"), str) or not cve["id"]:
                    fail("recipes[%r] has a CVE record with no id" % name)

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

    unscanned = report.get("unscanned_recipes")
    if isinstance(unscanned, list):
        for name in unscanned:
            if not isinstance(name, str) or not name:
                fail("unscanned_recipes holds %r, expected a recipe name" % name)

def _check_derived(report, fail):
    counts = report.get("counts")
    recipes = report.get("recipes")
    packages = report.get("packages")
    unscanned = report.get("unscanned_recipes")
    if not isinstance(counts, dict) or not isinstance(recipes, dict):
        return
    if not isinstance(packages, dict) or not isinstance(unscanned, list):
        return

    entries = [e for e in recipes.values() if isinstance(e, dict)]
    if len(entries) != len(recipes):
        # Shape errors are already reported; deriving from them adds noise.
        return

    packaged = [e for e in entries if e.get("packaged") is True]

    def cve_count(items):
        return sum(len(e["cves"]) for e in items if isinstance(e.get("cves"), list))

    derived = {
        "recipes": len(recipes),
        "packages": len(packages),
        "packaged_recipes": len(packaged),
        "cves": cve_count(entries),
        "packaged_cves": cve_count(packaged),
        "unscanned_recipes": len(unscanned),
    }

    for name, want in derived.items():
        got = counts.get(name)
        if _is_int(got) and got != want:
            fail("counts.%s is %d, but the report holds %d" % (name, got, want))

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
    args = parser.parse_args()

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
        extra = additions(report)

        for message in failures:
            print("%s: %s" % (path, message), file=sys.stderr)
        for message in extra:
            print("%s: unknown key, not in version %s: %s"
                  % (path, REPORT_VERSION, message), file=sys.stderr)

        if failures or (extra and args.strict):
            rc = 1
            continue

        counts = report.get("counts", {})
        print(
            "%s: ok, version %s, %d packages, %d recipes, %d CVEs "
            "(%d recipes, %d CVEs packaged), health counters zero"
            % (
                path,
                report.get("version"),
                counts.get("packages", 0),
                counts.get("recipes", 0),
                counts.get("cves", 0),
                counts.get("packaged_recipes", 0),
                counts.get("packaged_cves", 0),
            )
        )

    return rc

if __name__ == "__main__":
    raise SystemExit(main())
