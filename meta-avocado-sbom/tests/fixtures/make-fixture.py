#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""Cut a committable fixture out of a full CVE report.

Trims whole recipes and whole packages, never edits a record, and rewrites the
counters describing the trimmed set.

  python3 tests/fixtures/make-fixture.py FULL-REPORT.json \
      -o tests/fixtures/avocado-cve-report.json

Regenerate rather than hand-edit: a hand-edited fixture drifts from what the
generator would produce.
"""

import argparse
import json
import os
import sys

sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "lib"),
)

from avocado_sbom.report import packages_digest  # noqa: E402
from avocado_sbom.verify import HEALTH_COUNTERS  # noqa: E402

# Kept for the shapes they cover: packaged and unpackaged, one CVE and several.
KEEP_RECIPES = (
    "avahi",
    "libarchive",
    "libconfuse-native",
    "libpng",
    "libpng-native",
    "libxml2",
    "util-linux",
)

# Packages from recipes with no CVEs: most of a real package set is unreferenced.
EXTRA_PACKAGE_SAMPLE = 25

# Not re-derivable from a trimmed report, so carried unchanged. No check reads
# their value; package_collisions is here rather than below because it is not a
# health counter - the first pkgdata directory wins and the report is complete
# either way - so a source report carrying one still cuts a valid fixture.
CARRIED = (
    "cve_files",
    "manifests_read",
    "unpatched_cves",
    "ignored_cves",
    "patched_cves",
    "unknown_status_cves",
    "package_collisions",
)

def trim(full):
    recipes = {}
    for name in KEEP_RECIPES:
        if name not in full["recipes"]:
            raise SystemExit("source report has no recipe %r" % name)
        recipes[name] = full["recipes"][name]
        if "scope" not in full["recipes"][name]:
            raise SystemExit(
                "source report's %r has no scope; it predates the scope field "
                "and cannot be cut into a current fixture" % name
            )

    packages = {
        name: pkg
        for name, pkg in full["packages"].items()
        if pkg["recipe"] in recipes
    }

    others = sorted(
        name
        for name, pkg in full["packages"].items()
        if pkg["recipe"] not in recipes
    )
    step = max(1, len(others) // EXTRA_PACKAGE_SAMPLE)
    for name in others[::step][:EXTRA_PACKAGE_SAMPLE]:
        packages[name] = full["packages"][name]

    kept_recipes = {pkg["recipe"] for pkg in packages.values()}
    if "no_cve_record_recipes" not in full:
        raise SystemExit(
            "source report has no no_cve_record_recipes; it predates the split "
            "of unscanned_recipes and cannot be cut into a current fixture"
        )
    unscanned = [r for r in full["unscanned_recipes"] if r in kept_recipes]
    no_record = [r for r in full["no_cve_record_recipes"] if r in kept_recipes]

    packaged = [e for e in recipes.values() if e["packaged"]]
    # Derived, not carried: trimming can drop the one recipe a multi-kernel
    # machine built twice, and a carried figure would then describe versions
    # the fixture no longer holds.
    alt_records = [
        alt for e in recipes.values() for alt in e.get("alt_versions", ())
    ]
    on_device = [e for e in recipes.values() if e["scope"] != "build-only"]
    counts = {
        "recipes": len(recipes),
        "packages": len(packages),
        "packaged_recipes": len(packaged),
        "device_recipes": len(on_device),
        "cves": sum(len(e["cves"]) for e in recipes.values()),
        "packaged_cves": sum(len(e["cves"]) for e in packaged),
        "device_cves": sum(len(e["cves"]) for e in on_device),
        "unscanned_recipes": len(unscanned),
        "no_cve_record_recipes": len(no_record),
        "alt_recipes": sum(1 for e in recipes.values() if e.get("alt_versions")),
        "alt_cves": sum(len(alt["cves"]) for alt in alt_records),
    }
    for name in CARRIED:
        counts[name] = full["counts"][name]
    # A fixture with a non-zero health counter would pin the failure as normal.
    # Read from verify so the two cannot disagree about what a health counter is.
    for name in HEALTH_COUNTERS:
        if full["counts"][name]:
            raise SystemExit(
                "source report has counts.%s = %d; fix the build that produced "
                "it before cutting a fixture from it"
                % (name, full["counts"][name])
            )
        counts[name] = 0

    fixture = dict(full)
    fixture["counts"] = counts
    fixture["recipes"] = dict(sorted(recipes.items()))
    fixture["packages"] = dict(sorted(packages.items()))
    fixture["unscanned_recipes"] = unscanned
    fixture["no_cve_record_recipes"] = no_record
    fixture["packages_digest"] = packages_digest(packages)
    return fixture

def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("report", help="full report to cut down")
    parser.add_argument("-o", "--output", required=True)
    args = parser.parse_args()

    with open(args.report) as f:
        full = json.load(f)

    fixture = trim(full)
    with open(args.output, "w") as f:
        json.dump(fixture, f, indent=2, sort_keys=True)
        f.write("\n")

    counts = fixture["counts"]
    print(
        "%s: %d packages, %d recipes, %d CVEs (%d recipes packaged)"
        % (args.output, counts["packages"], counts["recipes"], counts["cves"],
           counts["packaged_recipes"])
    )

if __name__ == "__main__":
    main()
