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

# Not re-derivable from a trimmed report. Carried unchanged, never asserted on.
CARRIED = (
    "cve_files",
    "unpatched_cves",
    "ignored_cves",
    "patched_cves",
    "unknown_status_cves",
)

def trim(full):
    recipes = {}
    for name in KEEP_RECIPES:
        if name not in full["recipes"]:
            raise SystemExit("source report has no recipe %r" % name)
        recipes[name] = full["recipes"][name]

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
    unscanned = [r for r in full["unscanned_recipes"] if r in kept_recipes]

    packaged = [e for e in recipes.values() if e["packaged"]]
    counts = {
        "recipes": len(recipes),
        "packages": len(packages),
        "packaged_recipes": len(packaged),
        "cves": sum(len(e["cves"]) for e in recipes.values()),
        "packaged_cves": sum(len(e["cves"]) for e in packaged),
        "unscanned_recipes": len(unscanned),
    }
    for name in CARRIED:
        counts[name] = full["counts"][name]
    # A fixture with a non-zero health counter would pin the failure as normal.
    for name in ("stale_dropped", "cve_files_unreadable", "pkgdata_unreadable",
                 "package_collisions"):
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
