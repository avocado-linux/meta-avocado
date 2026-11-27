#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""Check a build tree against the feed contract.

Each check is a function returning (name, ok, detail). A check whose input is
absent fails; it is never skipped, and a check that depends on an optional flag
is left out of the list when the flag is absent, so the final count says which
checks ran.
"""

import glob
import json
import os

from avocado_sbom import report

COVERAGE_KEYS = frozenset(
    ("roots", "no_document", "unresolved_ids", "alt_included", "alt_not_covered")
)
LIST_KEYS = frozenset(("no_document", "alt_included", "alt_not_covered"))
SPDX_CONTEXT_PREFIX = "https://spdx.org/rdf/3."
# The scanner manifest lists each recipe's CVE products. A kernel is the recipe
# whose product is linux_kernel, which holds for an alternate-kernel build too
# (the same recipe at another version) and for a vendor kernel with any name.
KERNEL_PRODUCT = "linux_kernel"
FEED_PREFIX = "avocado-feed-"
# The recipe whose package collects the images directory.
BOOTFILES_RPM = "avocado-img-bootfiles-*.rpm"
# An RPM header is a few KiB; a file list of this package is well inside 8 MiB.
RPM_HEAD_BYTES = 8 * 1024 * 1024

def _load(path):
    """(data, None) or (None, why), so a check reports instead of raising."""
    try:
        with open(path) as f:
            return json.load(f), None
    except OSError as e:
        return None, "cannot read %s: %s" % (path, e.strerror)
    except ValueError as e:
        return None, "%s is not JSON: %s" % (path, e)

def _short_name(machine):
    prefix = "avocado-"
    return machine[len(prefix):] if machine.startswith(prefix) else machine

class Paths:
    def __init__(self, tmpdir, machine):
        short = _short_name(machine)
        deploy = os.path.join(tmpdir, "deploy")
        # The feed files sit with the report, not in the images directory: the
        # bootfiles package collects everything in that one (see
        # check_feed_files_not_in_images).
        feed_dir = os.path.join(deploy, "avocado-cve")
        stem = os.path.join(feed_dir, "avocado-feed-%s" % short)
        self.deploy = deploy
        self.images = os.path.join(deploy, "images", machine)
        self.document = stem + ".spdx.json"
        self.coverage = stem + ".coverage.json"
        self.manifest = stem + ".sbom-cve-check.yocto.json"
        self.report = os.path.join(
            feed_dir, "avocado-cve-report-%s.json" % machine)
        self.rpms = os.path.join(
            feed_dir, "avocado-rpm-manifest-%s.json" % machine)

def check_document_exists(paths):
    ok = os.path.isfile(paths.document)
    return ("feed-document-exists", ok,
            "" if ok else "no feed document at %s" % paths.document)

def _sbom_elements(document):
    graph = document.get("@graph") if isinstance(document, dict) else None
    if not isinstance(graph, list):
        return None
    return [e for e in graph
            if isinstance(e, dict) and e.get("type") == "software_Sbom"]

def check_document_jsonld(paths):
    name = "feed-document-jsonld"
    document, why = _load(paths.document)
    if why:
        return name, False, why
    context = document.get("@context") if isinstance(document, dict) else None
    contexts = context if isinstance(context, list) else [context]
    if not any(isinstance(c, str) and c.startswith(SPDX_CONTEXT_PREFIX)
               and c.endswith(".jsonld") for c in contexts):
        return name, False, "@context is %r, not the SPDX 3.0 context" % (context,)
    sboms = _sbom_elements(document)
    if sboms is None:
        return name, False, "no @graph list"
    if len(sboms) != 1:
        return name, False, "%d SBOM elements, expected exactly 1" % len(sboms)
    return name, True, ""

def check_document_roots(paths):
    name = "feed-document-roots"
    document, why = _load(paths.document)
    if why:
        return name, False, why
    coverage, why = _load(paths.coverage)
    if why:
        return name, False, why
    sboms = _sbom_elements(document) or []
    if len(sboms) != 1:
        return name, False, "%d SBOM elements, expected exactly 1" % len(sboms)
    roots = sboms[0].get("rootElement")
    count = len(roots) if isinstance(roots, list) else None
    expected = coverage.get("roots") if isinstance(coverage, dict) else None
    # True == 1 in Python, so a boolean in the record would read as a root count.
    if count is None or type(expected) is not int or count != expected:
        return name, False, ("SBOM has %s rootElement entries, coverage record "
                             "says roots is %r" % (count, expected))
    return name, True, ""

def check_coverage_record(paths):
    name = "coverage-record"
    coverage, why = _load(paths.coverage)
    if why:
        return name, False, why
    if not isinstance(coverage, dict):
        return name, False, "not a JSON object"
    keys = set(coverage)
    if keys != COVERAGE_KEYS:
        return name, False, "missing %s, unexpected %s" % (
            sorted(COVERAGE_KEYS - keys), sorted(keys - COVERAGE_KEYS))
    # The counts are integers and the rest lists; a record of another shape
    # would read as a complete scan to a consumer that trusts the key names.
    wrong = [key for key in sorted(COVERAGE_KEYS)
             if not isinstance(coverage[key], list if key in LIST_KEYS else int)
             or isinstance(coverage[key], bool)]
    if wrong:
        return name, False, "wrong value type for %s" % ", ".join(wrong)
    # do_feed_sbom writes no document with a hole in it.
    if coverage["unresolved_ids"]:
        return name, False, "%d unresolved identifier(s)" % coverage["unresolved_ids"]
    return name, True, ""

def check_feed_manifest(paths):
    ok = os.path.isfile(paths.manifest)
    return ("feed-manifest", ok,
            "" if ok else "no feed manifest at %s" % paths.manifest)

def check_no_document_copies(paths):
    """A copy of the document under the rpm or spdx tree would be picked up as a
    package or as a recipe document.
    """
    found = []
    base = os.path.basename(paths.document)
    for tree in ("rpm", "spdx"):
        for root, _dirs, files in os.walk(os.path.join(paths.deploy, tree)):
            if base in files:
                found.append(os.path.join(root, base))
    return ("no-document-copies", not found,
            "found %s" % ", ".join(sorted(found)) if found else "")

def check_feed_files_not_in_images(paths):
    """avocado-img-bootfiles packages every file in the images directory that its
    skip patterns do not name, so a feed document or scan export left there is
    built into an RPM of the feed, with its VEX statements and CVE assessment.
    """
    found = sorted(glob.glob(os.path.join(paths.images, FEED_PREFIX + "*")))
    return ("feed-files-not-in-images", not found,
            "found %s" % ", ".join(found) if found else "")

def check_feed_files_not_in_rpms(paths):
    """No bootfiles RPM lists a feed file. The check above is about where files
    sit now; this one is about what an earlier build already packaged, which a
    later build reuses from sstate without looking at the directory again.

    An RPM header names its files as plain strings ahead of the compressed
    payload, so reading the head of the file is enough.
    """
    leaked = []
    pattern = os.path.join(paths.deploy, "rpm", "**", BOOTFILES_RPM)
    for rpm in sorted(glob.glob(pattern, recursive=True)):
        try:
            with open(rpm, "rb") as f:
                head = f.read(RPM_HEAD_BYTES)
        except OSError as e:
            return ("feed-files-not-in-rpms", False,
                    "cannot read %s: %s" % (rpm, e.strerror))
        if FEED_PREFIX.encode() in head:
            leaked.append(rpm)
    return ("feed-files-not-in-rpms", not leaked,
            "lists a feed file: %s" % ", ".join(leaked) if leaked else "")

def _same_keys(name, ours_path, theirs_path):
    ours, why = _load(ours_path)
    if why:
        return name, False, why
    theirs, why = _load(theirs_path)
    if why:
        return name, False, why
    if not isinstance(ours, dict) or not isinstance(theirs, dict):
        return name, False, "top level is not a JSON object"
    if set(ours) != set(theirs):
        return name, False, "only here: %s; only in the image file: %s" % (
            sorted(set(ours) - set(theirs)), sorted(set(theirs) - set(ours)))
    return name, True, ""

def _read_manifest(path):
    """({(recipe, version): {status: count}}, kernel keys, None) of a manifest.

    A kernel is an entry that lists the CVE product linux_kernel, whatever the
    recipe is called: a name test would count firmware and header recipes, and
    miss a vendor kernel.
    """
    data, why = _load(path)
    if why:
        return None, None, why
    entries = data.get("package") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return None, None, "%s has no package list" % path
    out = {}
    kernels = set()
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            continue
        key = (entry["name"], report._strip_pe(str(entry.get("version", ""))))
        counts = out.setdefault(key, {})
        for product in entry.get("products") or []:
            if isinstance(product, dict) and product.get("product") == KERNEL_PRODUCT:
                kernels.add(key)
        for issue in entry.get("issue") or []:
            status = issue.get("status") if isinstance(issue, dict) else None
            # An unhashable status would raise here instead of being reported.
            if isinstance(status, str):
                counts[status] = counts.get(status, 0) + 1
    if not out:
        return None, None, "%s has no usable package entries" % path
    return out, kernels, None

def check_image_recipes(paths, image_manifest):
    name = "image-recipes"
    image, _kernels, why = _read_manifest(image_manifest)
    if why:
        return name, False, why
    feed, _kernels, why = _read_manifest(paths.manifest)
    if why:
        return name, False, why
    missing = sorted(set(image) - set(feed))
    if missing:
        return name, False, "%d of %d image recipes missing from the feed: %s" % (
            len(missing), len(image),
            ", ".join("%s %s" % key for key in missing[:10]))
    return name, True, ""

def check_image_kernels(paths, image_manifest):
    name = "image-kernels"
    image, image_kernels, why = _read_manifest(image_manifest)
    if why:
        return name, False, why
    feed, _kernels, why = _read_manifest(paths.manifest)
    if why:
        return name, False, why
    kernels = sorted(image_kernels)
    if not kernels:
        return name, False, "no recipe with the %s product in the image manifest" % (
            KERNEL_PRODUCT)
    bad = []
    for key in kernels:
        for status in ("Unpatched", "Ignored"):
            have = feed.get(key, {}).get(status, 0)
            want = image[key].get(status, 0)
            if have != want:
                bad.append("%s %s %s: feed %d, image %d"
                           % (key[0], key[1], status, have, want))
    return name, not bad, "; ".join(bad)

def run_checks(tmpdir, machine, image_manifest=None, image_report=None,
               image_rpm_manifest=None):
    paths = Paths(tmpdir, machine)
    results = [
        check_document_exists(paths),
        check_document_jsonld(paths),
        check_document_roots(paths),
        check_coverage_record(paths),
        check_feed_manifest(paths),
        check_no_document_copies(paths),
        check_feed_files_not_in_images(paths),
        check_feed_files_not_in_rpms(paths),
    ]
    if image_report:
        results.append(_same_keys("report-keys", paths.report, image_report))
    if image_rpm_manifest:
        results.append(
            _same_keys("rpm-manifest-keys", paths.rpms, image_rpm_manifest))
    if image_manifest:
        results.append(check_image_recipes(paths, image_manifest))
        results.append(check_image_kernels(paths, image_manifest))
    return results

def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(
        description="Check a build tree against the feed SBOM contract"
    )
    parser.add_argument("--tmpdir", required=True, help="build TMPDIR")
    parser.add_argument(
        "--machine", required=True, help="full MACHINE, e.g. avocado-raspberrypi5"
    )
    parser.add_argument("--image-manifest",
                        help="image-scope sbom-cve-check manifest to compare")
    parser.add_argument("--image-report",
                        help="image-scope CVE report whose top-level keys to match")
    parser.add_argument("--image-rpm-manifest",
                        help="image-scope RPM manifest whose top-level keys to match")
    args = parser.parse_args(argv)

    results = run_checks(args.tmpdir, args.machine, args.image_manifest,
                         args.image_report, args.image_rpm_manifest)
    for name, ok, detail in results:
        print("ok %s" % name if ok else "FAIL %s: %s" % (name, detail))
    passed = sum(1 for _n, ok, _d in results if ok)
    print("checks: %d/%d passed" % (passed, len(results)))
    return 0 if passed == len(results) else 1

if __name__ == "__main__":
    raise SystemExit(main())
