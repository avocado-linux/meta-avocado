# SPDX-License-Identifier: Apache-2.0

import datetime
import glob
import hashlib
import json
import os

class Stats(dict):
    _NAMES = (
        "packages",
        "builds",
        "alternate_builds",
        "cves",
        "packaged_builds",
        "packaged_cves",
        "cve_files",
        "cve_files_unreadable",
        "entries_unreadable",
        "pkgdata_unreadable",
        "package_collisions",
        "shared_package_builds",
        "stale_dropped",
        "unscanned_builds",
        "no_cve_record_builds",
        "not_covered_builds",
        "unpatched_cves",
        "ignored_cves",
        "patched_cves",
        "unknown_status_cves",
        "unverified_compiled_source_cves",
    )

    def __init__(self):
        super().__init__((name, 0) for name in self._NAMES)

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name) from None

    def __setattr__(self, name, value):
        if name not in self._NAMES:
            raise AttributeError("unknown counter %r" % name)
        self[name] = value

# The default multiconfig. A build is named by its recipe there, and by
# "<mc>:<recipe>" in an alternate multiconfig: the name do_feed_sbom gives that
# build's recipe package in the feed document (feedsbom.alt_label), so the one
# the scanner exports it under. Neither a recipe nor a multiconfig name can hold
# a colon, so the name parses back without ambiguity.
DEFAULT_MC = ""

def build_id(mc, recipe):
    return "%s:%s" % (mc, recipe) if mc else recipe

def split_build_id(name):
    """(mc, recipe) of a build name; DEFAULT_MC for a plain recipe name."""
    mc, sep, recipe = name.partition(":")
    if sep and mc and recipe:
        return mc, recipe
    return DEFAULT_MC, name

def normalize_version(version):
    """A version as a consumer compares it with an RPM's version-release: no
    leading epoch, and "-" where rpm spells "+"."""
    epoch, sep, rest = version.partition(":")
    if sep and epoch.isdigit():
        version = rest
    return version.replace("+", "-")

def _join_version(version, revision):
    if version and revision:
        return "%s-%s" % (version, revision)
    return version or ""

def _read_pkgdata_fields(path):
    fields = {}
    try:
        with open(path, errors="ignore") as f:
            for line in f:
                key, sep, value = line.partition(": ")
                if not sep:
                    continue
                if key in ("PN", "PV", "PKGV", "PKGR"):
                    fields[key] = value.strip()
                elif key.startswith(("PKGV:", "PKGR:")):
                    # A recipe that gives one of its packages its own version
                    # (lvm2's libdevmapper is 1.02.213 against lvm2's 2.03.39)
                    # writes PKGV:<package> and no plain PKGV in that package's
                    # runtime-reverse file. The file describes one package, so
                    # its single qualified key is the one that applies.
                    fields.setdefault(key.partition(":")[0] + ":pkg", value.strip())
    except OSError:
        return {}
    return fields

def _pkgdata_entries(pkgdata_dir, stats):
    """(package name, recipe, package version, version keys, PV) for each
    package one pkgdata directory names. The keys are PV and plain PKGV, the
    versions a manifest entry is matched against."""
    reverse_dir = os.path.join(pkgdata_dir, "runtime-reverse")
    if not os.path.isdir(reverse_dir):
        return

    for path in sorted(glob.glob(os.path.join(reverse_dir, "*"))):
        name = os.path.basename(path)
        fields = _read_pkgdata_fields(path)
        recipe = fields.get("PN")
        if not recipe:
            stats.pkgdata_unreadable += 1
            continue

        version = _join_version(
            fields.get("PKGV") or fields.get("PKGV:pkg"),
            fields.get("PKGR") or fields.get("PKGR:pkg"),
        )
        keys = {v for v in (fields.get("PV"), fields.get("PKGV")) if v}
        yield name, recipe, version, keys, fields.get("PV")

def read_pkgdata(pkgdata_dirs, stats):
    """{package name: {recipe, version, origin}} and {recipe: version keys} of
    the pkgdata directories, the first directory to name a package winning it.
    The feed tasks and the RPM manifest read a tree with it; the report reads
    the trees with read_trees."""
    packages = {}
    recipe_versions = {}

    for pkgdata_dir in pkgdata_dirs:
        origin = os.path.basename(pkgdata_dir.rstrip("/"))
        for name, recipe, version, keys, _pv in _pkgdata_entries(pkgdata_dir, stats):
            recipe_versions.setdefault(recipe, set()).update(keys)
            if name in packages:
                if (packages[name]["recipe"] != recipe or
                        packages[name]["version"] != version):
                    stats.package_collisions += 1
                continue
            packages[name] = {"recipe": recipe, "version": version, "origin": origin}

    stats.packages = len(packages)
    return packages, recipe_versions

def alt_tree_problem(pkgdata_dir, recipes):
    """Why an alternate multiconfig's pkgdata cannot stand for it, or None.

    Read as it is, a tree missing a declared recipe leaves that recipe's
    packages out of the report and the RPM manifest while both still pass:
    the default multiconfig's packages carry every other check. recipes None
    asks only for some readable package.
    """
    if not os.path.isdir(os.path.join(pkgdata_dir, "runtime-reverse")):
        return "%s has no runtime-reverse directory" % pkgdata_dir
    found = {recipe for _n, recipe, _v, _k, _pv in _pkgdata_entries(pkgdata_dir, Stats())}
    if recipes is None:
        return None if found else "%s holds no readable package data" % pkgdata_dir
    missing = sorted(set(recipes) - found)
    if missing:
        return "%s holds no package of %s" % (pkgdata_dir, ", ".join(missing))
    return None

def _new_build(recipe, mc, packaged):
    return {"recipe": recipe, "mc": mc, "keys": set(), "pvs": set(), "version": "",
            "packaged": packaged}

def _add_package_build(packages, name, version, bid, builds, rank, stats):
    """File one package build under (name, normalized version), which a
    consumer joins an RPM on, so it is unique per name.

    Two trees that built one recipe into the same name-version-release built
    one RPM path, and the feed serves one file there: the default
    multiconfig's when the default built it, else that of the alternate the
    multikernel merge published first, since the merge never replaces a file
    already in the feed. The RPM manifest lists that file once, so the package
    build is its builder's, rank giving the merge order, even when the feed
    document left that build out. The same name and version from another
    recipe is a collision, and the first one stays.
    """
    by_version = packages.setdefault(name, {})
    key = normalize_version(version)
    held = by_version.get(key)
    if held is None:
        by_version[key] = {"version": version, "build": bid}
        return
    if builds[held["build"]]["recipe"] != builds[bid]["recipe"]:
        stats.package_collisions += 1
        return
    stats.shared_package_builds += 1
    if builds[held["build"]]["mc"] and rank(bid) < rank(held["build"]):
        by_version[key] = {"version": version, "build": bid}

def alt_merge_order(pairs, by_multiconfig=False):
    """The alternate builds in the order the multikernel merge publishes them.

    pairs are (mc, recipe) in AVOCADO_MULTIKERNEL_MC_RECIPES order. wrynose's
    merge publishes pair by pair; scarthgap's publishes a multiconfig's whole
    tree at its first pair, so by_multiconfig ranks every build of a
    multiconfig there.
    """
    if by_multiconfig:
        firsts = list(dict.fromkeys(mc for mc, _recipe in pairs))
        pairs = [(mc, recipe) for first in firsts for mc, recipe in pairs if mc == first]
    return [build_id(mc, recipe) for mc, recipe in pairs]


def read_trees(pkgdata_dirs, alt_trees, stats, merge_order=()):
    """(builds, packages) of a build's pkgdata.

    pkgdata_dirs are the default multiconfig's, read as one tree: the first
    directory to name a package wins it, as package names are unique within a
    tree. alt_trees are the alternate multiconfigs' (mc, pkgdata_dir,
    recipes): its pkgdata, and the recipes of it that reach the feed
    (AVOCADO_MULTIKERNEL_MC_RECIPES), the only ones read; None reads every
    recipe. merge_order lists the alternate builds as the multikernel merge
    publishes them, AVOCADO_MULTIKERNEL_MC_RECIPES order; one it does not list
    follows them, in the order read.

    builds maps each build id to its recipe, multiconfig, version keys, PV and
    "packaged". packages maps each package name to its package builds,
    {normalized version: {version, build}}.
    """
    order = {}
    for bid in merge_order:
        order.setdefault(bid, len(order))

    def rank(bid):
        return order.get(bid, len(order))

    builds = {}
    packages = {}
    default_names = {}

    def add(mc, name, recipe, version, keys, pv):
        bid = build_id(mc, recipe)
        build = builds.get(bid)
        if build is None:
            build = builds[bid] = _new_build(recipe, mc, True)
        build["keys"].update(keys)
        if pv:
            build["pvs"].add(pv)
        return bid

    for pkgdata_dir in pkgdata_dirs:
        for name, recipe, version, keys, pv in _pkgdata_entries(pkgdata_dir, stats):
            bid = add(DEFAULT_MC, name, recipe, version, keys, pv)
            if name in default_names:
                if default_names[name] != (recipe, version):
                    stats.package_collisions += 1
                continue
            default_names[name] = (recipe, version)
            _add_package_build(packages, name, version, bid, builds, rank, stats)

    for mc, pkgdata_dir, recipes in alt_trees:
        if not mc:
            raise ValueError("an alternate tree needs its multiconfig: %s" % pkgdata_dir)
        for name, recipe, version, keys, pv in _pkgdata_entries(pkgdata_dir, stats):
            if recipes is not None and recipe not in recipes:
                continue
            bid = add(mc, name, recipe, version, keys, pv)
            _add_package_build(packages, name, version, bid, builds, rank, stats)

    for build in builds.values():
        # PV names the build; a package without one leaves its PKGV.
        versions = build.pop("pvs") or build["keys"]
        build["version"] = min(versions) if versions else ""
    stats.packages = sum(len(v) for v in packages.values())
    return builds, packages

CVE_FIELDS = (
    "id",
    "summary",
    "description",
    "detail",
    "scorev2",
    "scorev3",
    "scorev4",
    "vector",
    "vectorString",
    "link",
)

# Dropped by --no-summary. Both are free prose and dominate the file size.
CVE_SUMMARY_FIELDS = ("summary", "description")
# The whole vocabulary the manifest emits: sbom-cve-check maps every VEX status
# it computed onto one of these three (fixed -> Patched, affected and
# under_investigation -> Unpatched, not_affected -> Ignored). Filtering on
# anything else would match no issue at all and produce an empty,
# CVE-free-looking report.
CVE_STATUSES = ("Unpatched", "Patched", "Ignored")
# A report may list one of those, or all three with a status on every CVE.
STATUS_ALL = "All"
REPORT_STATUSES = CVE_STATUSES + (STATUS_ALL,)

# What each build's record says about its scan. "scanned" carries the CVEs at
# the report's status, an empty list being clean at it; "no-cve-record" was
# scanned and matched no CVE record; "unscanned" has no usable entry.
COVERAGE_SCANNED = "scanned"
COVERAGE_NO_RECORD = "no-cve-record"
COVERAGE_UNSCANNED = "unscanned"
COVERAGES = (COVERAGE_SCANNED, COVERAGE_NO_RECORD, COVERAGE_UNSCANNED)

# sbom-cve-check names each export after the SBOM it scanned, with the
# extension from SBOM_CVE_CHECK_EXPORT_CVECHECK[ext], and deploys it to
# ${DEPLOY_DIR_IMAGE}. This layer scans the whole build in one pass, through
# OE-core's meta-world-recipe-sbom, so there is normally exactly one.
MANIFEST_SUFFIX = ".sbom-cve-check.yocto.json"
WORLD_SBOM_NAME = "world-recipe-sbom"
WORLD_MANIFEST = WORLD_SBOM_NAME + MANIFEST_SUFFIX

def find_manifests(path):
    """Manifests under `path`, which may be one file or a directory of them."""
    if os.path.isdir(path):
        return sorted(glob.glob(os.path.join(path, "*" + MANIFEST_SUFFIX)))
    return [path] if os.path.exists(path) else []

_FILTERED_COUNTER = {
    "Unpatched": "unpatched_cves",
    "Patched": "patched_cves",
    "Ignored": "ignored_cves",
}

def _strip_pe(version):
    """Drop the EXTENDPE prefix the manifest can carry in front of PV, as in
    "1_1.20.0".
    """
    epoch, sep, rest = version.partition("_")
    if sep and epoch.isdigit():
        return rest
    return version

class Coverage:
    """What the manifests say about each build beyond its CVEs.

    seen       builds with at least one readable entry at a version this
               build has
    matched    of those, the ones where some such entry matched a CVE record:
               a non-empty "issue" list
    assessed   of those, the ones where some such entry carried an issue with
               a status this report knows
    """

    def __init__(self):
        self.seen = set()
        self.matched = set()
        self.assessed = set()

    @property
    def no_record(self):
        """Scanned, and every copy came back with nothing matched.

        sbom-cve-check exports an entry for every component it scanned, with an
        empty "issue" list when no CVE record names its identifiers or it has
        none. cvesInRecord adds nothing: the tool sets it from that same list.
        """
        return self.seen - self.matched

# What sbom-cve-check 1.4.0 writes for a CVE its compiled-source filter drops:
# the record names the files the fix touches and none is in the build's list of
# sources (analysis/compiled_sources.py). A recipe's own CVE_STATUS can carry the
# same detail, with its own reason as the description, so both are matched.
COMPILED_SOURCE_DETAIL = "not-applicable-config"
COMPILED_SOURCE_DESCRIPTION = "vulnerable_code_not_present: Source code not compiled by config"
# The CPE product of a kernel. The scanner uses a kernel's list only when it
# names files every kernel build compiles, so only a real source walk passes.
KERNEL_PRODUCT = "linux_kernel"

def trusts_compiled_sources(build, products, compiled_sources):
    """Whether the compiled-source filter's result stands for this build.

    The scanner reads the build's source files as the recipe's compiled sources.
    A recipe built with SPDX_INCLUDE_COMPILED_SOURCES lists what its build
    compiled; any other lists only what it fetched, so a CVE in a file it never
    fetched by name reads as not compiled. compiled_sources tells, for a build
    id, whether it was built with the setting, or is None when the report does
    not know it (a report written before it carried the flag): then only
    kernels are trusted, which is every recipe the setting was ever made for,
    and for which the scanner rejects a list that did not come from a source
    walk.

    do_cve_report reads the setting from its own datastore, which sees the
    same :pn- lines a recipe's parse does. A recipe that turns it off in its
    own parse (linux-yocto with module-signing) writes no source walk, and as
    a kernel its fetched-only list is rejected by the scanner anyway.
    """
    if compiled_sources is None:
        return KERNEL_PRODUCT in products
    return bool(compiled_sources(build))

def _is_compiled_source_ignore(issue):
    return (issue.get("status") == "Ignored"
            and issue.get("detail") == COMPILED_SOURCE_DETAIL
            and issue.get("description") == COMPILED_SOURCE_DESCRIPTION)

def _listed_status(item, status):
    """A listed CVE's status: its own at status All, else the report's."""
    return item.get("status", status)

def _entry_products(entry):
    products = entry.get("products")
    if not isinstance(products, list):
        return set()
    return {p["product"] for p in products
            if isinstance(p, dict) and isinstance(p.get("product"), str)}

def read_cve_data(manifests, builds, stats, status="Unpatched", summary=True,
                  compiled_sources=None):
    """The build id -> record map, and the Coverage the manifests give.

    builds is read_trees' map. An entry belongs to the build it is named after:
    "<mc>:<recipe>" to that alternate build, any other name to the default
    multiconfig's build of that recipe. One for a build with no package data
    (a native, a deploy-only recipe) adds that build to builds, unpackaged.

    compiled_sources is a function telling whether a build id's
    compiled-source list may be trusted, or None (see trusts_compiled_sources).
    Any other build's CVE the filter dropped is listed as Unpatched with no
    detail (the filter replaced the scanner's version result, so which one it
    was is unknown), with what the scanner said under "scanner".
    """
    fields = (
        CVE_FIELDS
        if summary
        else tuple(f for f in CVE_FIELDS if f not in CVE_SUMMARY_FIELDS)
    )
    listed = set(CVE_STATUSES) if status == STATUS_ALL else {status}
    coverage = Coverage()
    # {build id: record}, in manifest order.
    records = {}

    paths = sorted(manifests)
    stats.cve_files = len(paths)

    for path in paths:
        try:
            with open(path) as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            stats.cve_files_unreadable += 1
            continue

        entries = data.get("package") if isinstance(data, dict) else None
        if not isinstance(entries, list) or not all(
            isinstance(e, dict) for e in entries):
            stats.cve_files_unreadable += 1
            continue

        # A malformed entry costs that entry, not the manifest: the whole build
        # is described by a single file here, and treating one bad record as an
        # unreadable file would make cve_files_unreadable >= cve_files - the
        # "nothing was scanned" condition - out of a report that scanned
        # everything else fine.
        for entry in entries:
            name = entry.get("name")
            version = entry.get("version", "")
            if not isinstance(name, str) or not name or not isinstance(version, str):
                stats.entries_unreadable += 1
                continue

            # An entry scanned at a version this build does not have says
            # nothing about the version it does have, so it does not count as
            # seen: a build with no other entry is unscanned.
            build = builds.get(name)
            known = build["keys"] if build else None
            stripped = _strip_pe(version)
            if not known:
                version = stripped
            elif version not in known:
                if stripped not in known:
                    stats.stale_dropped += 1
                    continue
                version = stripped

            # sbom-cve-check always writes the key, empty when nothing matched.
            # Without it the entry says nothing, which is not "no record".
            raw_issues = entry.get("issue")
            if not isinstance(raw_issues, list) or not all(
                isinstance(i, dict) for i in raw_issues):
                stats.entries_unreadable += 1
                continue

            if build is None:
                mc, recipe = split_build_id(name)
                build = builds[name] = _new_build(recipe, mc, False)
                del build["pvs"]
                build["version"] = version

            coverage.seen.add(name)
            if raw_issues:
                coverage.matched.add(name)

            trusted = trusts_compiled_sources(name, _entry_products(entry), compiled_sources)
            issues = []
            for issue in raw_issues:
                issue_status = issue.get("status")
                scanner = None
                if not trusted and _is_compiled_source_ignore(issue):
                    scanner = {k: issue[k] for k in ("status", "detail", "description")}
                    issue = {k: v for k, v in issue.items() if k not in scanner}
                    issue_status = "Unpatched"
                if issue_status in CVE_STATUSES:
                    coverage.assessed.add(name)
                if issue_status in listed:
                    item = {k: issue[k] for k in fields if k in issue}
                    if scanner:
                        item["scanner"] = scanner
                    if status == STATUS_ALL:
                        # One status is implied by the report's own "status";
                        # a report of every status has to say which each CVE is.
                        item["status"] = issue_status
                    issues.append(item)
                    continue

                counter = _FILTERED_COUNTER.get(issue_status)
                if counter:
                    stats[counter] += 1
                else:
                    stats.unknown_status_cves += 1

            if not issues:
                continue

            record = records.get(name)
            if record is None:
                record = records[name] = {"version": version, "cves": []}
            # Two entries for one build: a directory of manifests, where a
            # per-image export sits beside the world one, or a multilib
            # variant. Merge by CVE id rather than overwrite, or the counts
            # would keep the CVEs the report body just lost.
            # A CVE another manifest reports Unpatched outright wins over one
            # this report turned to unverified, whichever manifest came first;
            # otherwise the first manifest's stands.
            at = {c.get("id"): n for n, c in enumerate(record["cves"])}
            for item in issues:
                n = at.get(item.get("id"))
                if n is None:
                    at[item.get("id")] = len(record["cves"])
                    record["cves"].append(item)
                elif ("scanner" in record["cves"][n] and "scanner" not in item
                      and _listed_status(item, status) == "Unpatched"):
                    record["cves"][n] = item

    return records, coverage

REPORT_VERSION = "2"
# The versions build_report_from_anchor reads.
ANCHOR_VERSIONS = ("1", "2")

class AnchorUnsupported(ValueError):
    """A version 1 report of a build with alternate multiconfig content. Its
    feed document names no build apart, and the report already filed the
    alternate builds by recipe and version, so a rebuild from it would carry
    version 1's binding in version 2's shape."""

def build_report(manifests, pkgdata_dirs, machine=None, status="Unpatched", summary=True,
                 alt_trees=(), compiled_sources=None, not_covered=None, merge_order=()):
    """alt_trees are the alternate multiconfigs' (mc, pkgdata_dir, recipes),
    read after pkgdata_dirs; see read_trees. compiled_sources names the
    recipes whose every build was built with SPDX_INCLUDE_COMPILED_SOURCES, or
    is a function of (mc, recipe) telling whether that build was, asked for
    every build in package data, or is None when that is not known; see
    trusts_compiled_sources. not_covered is
    {build id: reason} for the alternate builds the feed document left out
    (not_covered_builds). The report carries both per build. merge_order
    lists the alternate builds in AVOCADO_MULTIKERNEL_MC_RECIPES order; see
    read_trees."""
    if status not in REPORT_STATUSES:
        raise ValueError(
            "unknown CVE status %r; expected one of %s"
            % (status, ", ".join(REPORT_STATUSES))
        )

    not_covered = dict(not_covered or {})
    stats = Stats()
    builds, packages = read_trees(pkgdata_dirs, alt_trees, stats, merge_order)
    trust = None
    if compiled_sources is not None:
        # Decided per build in package data, as the build asks: the flags on
        # those builds are then all a rebuild needs to trust the same ones.
        # Any other build, one only a scan entry names, is not trusted.
        if callable(compiled_sources):
            asked = compiled_sources
        else:
            named = set(compiled_sources)
            asked = lambda _mc, recipe: recipe in named
        trust = _build_trust(bid for bid, b in builds.items()
                             if asked(b["mc"], b["recipe"]))
    return _assemble(manifests, builds, packages, stats, machine, status, summary,
                     trust, not_covered)

def _build_trust(bids):
    trusted = frozenset(bids)
    return lambda bid: bid in trusted

def not_covered_builds(coverage_record):
    """{build id: reason} of the alternate builds a feed coverage record lists
    in alt_not_covered. A malformed list entry names no multiconfig, so no
    build, and is left out."""
    found = {}
    entries = coverage_record.get("alt_not_covered") if isinstance(coverage_record, dict) else None
    if not isinstance(entries, list):
        raise ValueError("the coverage record has no alt_not_covered list")
    for item in entries:
        if not isinstance(item, dict):
            raise ValueError("alt_not_covered holds %r, not an object" % (item,))
        mc, recipe, reason = item.get("mc"), item.get("recipe"), item.get("reason")
        if not all(isinstance(v, str) for v in (mc, recipe, reason)):
            raise ValueError("alt_not_covered holds %r" % (item,))
        if mc and recipe:
            found.setdefault(build_id(mc, recipe), reason)
    return found

def packages_digest(packages):
    """sha256 over each package build, sorted by name, version and
    multiconfig: "name\\trecipe\\tversion\\n" for the default multiconfig's,
    "name\\trecipe\\tversion\\tmc\\n" for an alternate's. A build of one tree
    gets the same digest a version 1 report of it carried."""
    rows = []
    for name, entries in packages.items():
        for entry in entries:
            mc, recipe = split_build_id(entry["build"])
            rows.append((name, entry["version"], mc, recipe))
    digest = hashlib.sha256()
    for name, version, mc, recipe in sorted(rows):
        line = "%s\t%s\t%s\n" % (name, recipe, version) if not mc else \
            "%s\t%s\t%s\t%s\n" % (name, recipe, version, mc)
        digest.update(line.encode())
    return "sha256:" + digest.hexdigest()

def _packages_digest_v1(packages):
    digest = hashlib.sha256()
    for name in sorted(packages):
        pkg = packages[name]
        digest.update(
            ("%s\t%s\t%s\n" % (name, pkg["recipe"], pkg["version"])).encode()
        )
    return "sha256:" + digest.hexdigest()

def _anchor_error(path, what):
    return ValueError("%s: %s" % (path, what))

def _is_count(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0

def _anchor_common(anchor, path, carried_keys):
    for key in ("machine", "distro_version"):
        value = anchor.get(key)
        if key in anchor and not (isinstance(value, str) and value):
            raise _anchor_error(path, "%s is malformed" % key)
    counts = anchor.get("counts")
    if not isinstance(counts, dict):
        raise _anchor_error(path, "counts is missing")
    carried = {}
    for key in carried_keys:
        if not _is_count(counts.get(key)):
            raise _anchor_error(path, "counts.%s is missing or malformed" % key)
        carried[key] = counts[key]
    return carried

class _AnchorParts:
    """What a rebuild takes from a previous report: the packaged builds, the
    package builds, the counters pkgdata set, the compiled-source trust, the
    builds left out of the document and whether CVE descriptions were kept."""

    def __init__(self, builds, packages, carried, trust, not_covered, summary):
        self.builds = builds
        self.packages = packages
        self.carried = carried
        self.trust = trust
        self.not_covered = not_covered
        self.summary = summary

def _anchor_v2(anchor, path):
    records = anchor.get("builds")
    if not isinstance(records, dict) or not records:
        raise _anchor_error(path, "builds is missing, empty or malformed")
    builds = {}
    flags = {}
    not_covered = {}
    for bid, record in records.items():
        ok = (isinstance(bid, str) and isinstance(record, dict)
              and isinstance(record.get("recipe"), str) and record["recipe"]
              and isinstance(record.get("mc"), str)
              and bid == build_id(record["mc"], record["recipe"])
              and isinstance(record.get("version"), str)
              and isinstance(record.get("packaged"), bool)
              and record.get("coverage") in COVERAGES)
        # Required on a packaged build, as without them every scan entry of
        # its name would pass the stale-version check; empty is a package
        # pkgdata gives no version.
        if ok and record["packaged"] and "version_keys" not in record:
            raise _anchor_error(path, "builds[%r] is packaged and has no version_keys"
                                % (bid,))
        keys = record.get("version_keys", []) if ok else None
        if ok and not (isinstance(keys, list) and all(isinstance(k, str) and k for k in keys)):
            ok = False
        if ok and "compiled_sources" in record and not isinstance(record["compiled_sources"], bool):
            ok = False
        if ok and "not_covered" in record and not (
                isinstance(record["not_covered"], str) and record["not_covered"]):
            ok = False
        if not ok:
            raise _anchor_error(path, "builds[%r] is malformed" % (bid,))
        if "compiled_sources" in record:
            flags[bid] = record["compiled_sources"]
        if "not_covered" in record:
            not_covered[bid] = record["not_covered"]
        # Only what pkgdata said is carried; the scan says the rest again.
        if record["packaged"]:
            build = _new_build(record["recipe"], record["mc"], True)
            del build["pvs"]
            build["keys"] = set(keys)
            build["version"] = record["version"]
            builds[bid] = build
    if flags and len(flags) != len(records):
        raise _anchor_error(path, "compiled_sources is on some builds and not others")
    trust = None
    if flags:
        trust = _build_trust(bid for bid, flag in flags.items()
                             if flag and records[bid]["packaged"])

    packages_in = anchor.get("packages")
    if not isinstance(packages_in, dict) or not packages_in:
        raise _anchor_error(path, "packages is missing, empty or malformed")
    packages = {}
    for name, entries in packages_in.items():
        if not (isinstance(name, str) and isinstance(entries, list) and entries):
            raise _anchor_error(path, "packages[%r] is malformed" % (name,))
        seen = set()
        for entry in entries:
            # An empty version is a package pkgdata gives none, which no RPM
            # joins; a version 1 report kept it, and its digest covers it.
            if not (isinstance(entry, dict) and isinstance(entry.get("version"), str)
                    and isinstance(entry.get("build"), str) and entry["build"] in builds):
                raise _anchor_error(path, "packages[%r] names no packaged build: %r"
                                    % (name, entry))
            key = normalize_version(entry["version"])
            if key in seen:
                raise _anchor_error(path, "packages[%r] lists version %s twice"
                                    % (name, entry["version"]))
            seen.add(key)
        packages[name] = [{"version": e["version"], "build": e["build"]} for e in entries]
    if anchor.get("packages_digest") != packages_digest(packages):
        raise _anchor_error(path, "packages do not match packages_digest")

    summary = anchor.get("summary", True)
    if not isinstance(summary, bool):
        raise _anchor_error(path, "summary is malformed")
    carried = _anchor_common(anchor, path, ("pkgdata_unreadable", "package_collisions",
                                            "shared_package_builds"))
    return _AnchorParts(builds, packages, carried, trust, not_covered, summary)

def _anchor_v1(anchor, path):
    """A version 1 report of one tree, upgraded: every package is the default
    multiconfig's build of its recipe. Refused, as AnchorUnsupported, for a
    report with alternate multiconfig content."""
    if "recipe_versions" not in anchor:
        raise _anchor_error(
            path, "no recipe_versions; the build was scanned before the report "
            "carried them, so it cannot be rebuilt from a later scan")

    packages_in = anchor.get("packages")
    if not isinstance(packages_in, dict) or not packages_in or not all(
            isinstance(n, str) and isinstance(p, dict)
            and all(isinstance(p.get(k), str) for k in ("recipe", "version", "origin"))
            for n, p in packages_in.items()):
        raise _anchor_error(path, "packages is missing, empty or malformed")

    versions = anchor["recipe_versions"]
    if not isinstance(versions, dict) or not all(
            isinstance(v, list) and v and all(isinstance(x, str) and x for x in v)
            for v in versions.values()):
        raise _anchor_error(path, "recipe_versions is malformed")

    if anchor.get("packages_digest") != _packages_digest_v1(packages_in):
        raise _anchor_error(path, "packages do not match packages_digest")

    records = anchor.get("recipes")
    if records is not None and not isinstance(records, dict):
        raise _anchor_error(path, "recipes is malformed")
    records = records or {}
    alt_packages = anchor.get("alt_packages", {})
    if not isinstance(alt_packages, dict):
        raise _anchor_error(path, "alt_packages is malformed")
    alternates = set(alt_packages)
    alternates.update(r for r, record in records.items()
                      if isinstance(record, dict) and record.get("alt_versions"))
    if alternates:
        raise AnchorUnsupported(
            "%s: a version 1 report with alternate multiconfig builds of %s; its "
            "document does not name those builds apart, so it is not rebuilt as "
            "version 2" % (path, ", ".join(sorted(alternates))))

    compiled = None
    if "compiled_source_recipes" in anchor:
        compiled = anchor["compiled_source_recipes"]
        if not isinstance(compiled, list) or not all(
                isinstance(r, str) and r for r in compiled):
            raise _anchor_error(path, "compiled_source_recipes is malformed")
        compiled = set(compiled)

    carried = _anchor_common(anchor, path, ("pkgdata_unreadable", "package_collisions"))
    carried["shared_package_builds"] = 0

    builds = {}
    for recipe in set(versions) | {p["recipe"] for p in packages_in.values()}:
        build = _new_build(recipe, DEFAULT_MC, True)
        del build["pvs"]
        build["keys"] = set(versions.get(recipe, ()))
        # Version 1 does not say which key is PV. The record's version is the
        # scanner's, which reads PV; without a record the lowest key, which
        # PV is wherever PKGV extends it.
        record = records.get(recipe)
        version = record.get("version") if isinstance(record, dict) else None
        if not (isinstance(version, str) and version in build["keys"]):
            version = min(build["keys"]) if build["keys"] else ""
        build["version"] = version
        builds[recipe] = build
    packages = {n: [{"version": p["version"], "build": p["recipe"]}]
                for n, p in packages_in.items()}
    if packages_digest(packages) != anchor["packages_digest"]:
        raise _anchor_error(path, "the upgraded packages do not match packages_digest")
    trust = None
    if compiled is not None:
        trust = _build_trust(compiled & set(builds))
    return _AnchorParts(builds, packages, carried, trust, {}, True)

def _anchor_parts(anchor, path):
    if not isinstance(anchor, dict):
        raise _anchor_error(path, "not a CVE report object")
    version = anchor.get("version")
    if version == "2":
        return _anchor_v2(anchor, path)
    if version == "1":
        return _anchor_v1(anchor, path)
    raise _anchor_error(path, "report version %r, expected one of %s"
                        % (version, ", ".join(repr(v) for v in ANCHOR_VERSIONS)))

def build_report_from_anchor(manifests, anchor, status=None, summary=None,
                             anchor_path="anchor report"):
    """The report build_report would have written for `manifests`, from a
    previous report of the same build instead of its pkgdata.

    `anchor` is that report as parsed, version 2 or a version 1 report of one
    tree, which is upgraded with its packages_digest unchanged. A version 1
    report with alternate multiconfig content raises AnchorUnsupported, and
    one written before recipe_versions were added is refused. machine,
    distro_version and, unless given, the status and whether CVE descriptions
    are kept (version 2 records it; version 1 keeps them) come from it.
    """
    parts = _anchor_parts(anchor, anchor_path)
    if status is None:
        status = anchor.get("status")
    if status not in REPORT_STATUSES:
        raise ValueError(
            "unknown CVE status %r; expected one of %s"
            % (status, ", ".join(REPORT_STATUSES))
        )
    if summary is None:
        summary = parts.summary

    stats = Stats()
    stats.packages = sum(len(v) for v in parts.packages.values())
    for key, value in parts.carried.items():
        stats[key] = value
    packages = {name: {normalize_version(e["version"]): dict(e) for e in entries}
                for name, entries in parts.packages.items()}
    report, stats = _assemble(manifests, parts.builds, packages, stats,
                              anchor.get("machine"), status, summary, parts.trust,
                              parts.not_covered)
    if anchor.get("distro_version"):
        report["distro_version"] = anchor["distro_version"]
    return report, stats

def _assemble(manifests, builds, packages, stats, machine, status, summary,
              trust=None, not_covered=None):
    not_covered = not_covered or {}
    records, coverage = read_cve_data(
        manifests, builds, stats, status=status, summary=summary,
        compiled_sources=trust,
    )

    # Every packaged build is in exactly one coverage state. A consumer reads
    # "scanned" with no CVEs as clean, so a build gets it only when its
    # entries matched CVEs at a status this report knows and listed none at its
    # status, or listed some. Anything short of that is unscanned: no entry,
    # only entries at a version this build does not have, only unreadable ones,
    # or only issues of an unknown status. A build the feed document left out
    # has no entry of its own, and says why.
    out = {}
    for bid in sorted(builds):
        build = builds[bid]
        record = {"recipe": build["recipe"], "mc": build["mc"],
                  "version": build["version"], "packaged": build["packaged"]}
        if build["packaged"]:
            record["version_keys"] = sorted(build["keys"])
        if trust is not None:
            record["compiled_sources"] = bool(trust(bid))
        if bid in not_covered:
            record["coverage"] = COVERAGE_UNSCANNED
            record["not_covered"] = not_covered[bid]
        elif bid in records:
            record["coverage"] = COVERAGE_SCANNED
            record["cves"] = records[bid]["cves"]
        elif bid in coverage.assessed:
            record["coverage"] = COVERAGE_SCANNED
            record["cves"] = []
        elif bid in coverage.no_record:
            record["coverage"] = COVERAGE_NO_RECORD
        else:
            record["coverage"] = COVERAGE_UNSCANNED
        out[bid] = record

    for record in out.values():
        cves = record.get("cves", [])
        stats.cves += len(cves)
        if record["mc"]:
            stats.alternate_builds += 1
        if record["packaged"]:
            stats.packaged_builds += 1
            stats.packaged_cves += len(cves)
            if record["coverage"] == COVERAGE_UNSCANNED:
                stats.unscanned_builds += 1
            elif record["coverage"] == COVERAGE_NO_RECORD:
                stats.no_cve_record_builds += 1
        if "not_covered" in record:
            stats.not_covered_builds += 1
        for cve in cves:
            if "scanner" in cve:
                stats.unverified_compiled_source_cves += 1
            if status == STATUS_ALL:
                # What the report lists, counted off the report, so a CVE
                # two entries share is counted once: unpatched_cves +
                # patched_cves + ignored_cves equals cves.
                stats[_FILTERED_COUNTER[cve["status"]]] += 1
    stats.builds = len(out)

    package_builds = {
        name: sorted(by_version.values(), key=lambda e: (e["version"], e["build"]))
        for name, by_version in sorted(packages.items())
    }

    report = {
        "version": REPORT_VERSION,
        "generated": datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "packages_digest": packages_digest(package_builds),
        "status": status,
        # Whether CVE descriptions were kept, for a rebuild to keep the same.
        "summary": bool(summary),
        "counts": {key: stats[key] for key in (
            "builds",
            "alternate_builds",
            "packaged_builds",
            "cves",
            "packaged_cves",
            "packages",
            "shared_package_builds",
            "package_collisions",
            "unscanned_builds",
            "no_cve_record_builds",
            "not_covered_builds",
            "cve_files",
            "stale_dropped",
            "cve_files_unreadable",
            "entries_unreadable",
            "pkgdata_unreadable",
            "unpatched_cves",
            "ignored_cves",
            "patched_cves",
            "unknown_status_cves",
            "unverified_compiled_source_cves",
        )},
        "builds": out,
        "packages": package_builds,
    }
    if machine:
        report["machine"] = machine

    return report, stats

def write_report(report, out_path):
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    tmp_path = out_path + ".tmp"
    try:
        with open(tmp_path, "w") as f:
            json.dump(report, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp_path, out_path)
    except BaseException:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

    return out_path

def default_paths(tmpdir, machine=None):
    """Locate both sources under a build's TMPDIR.

    sbom-cve-check deploys its manifests to ${DEPLOY_DIR_IMAGE}, which is
    ${DEPLOY_DIR}/images/${MACHINE} and so already machine-scoped. A build that
    redirects DEPLOY_DIR away from ${TMPDIR}/deploy needs --manifest.
    """
    deploy_images = os.path.join(tmpdir, "deploy", "images")
    if machine:
        manifests = find_manifests(os.path.join(deploy_images, machine))
    else:
        scoped = sorted(
            d
            for d in glob.glob(os.path.join(deploy_images, "*"))
            if os.path.isdir(d) and find_manifests(d)
        )
        if len(scoped) > 1:
            raise ValueError(
                "%s holds sbom-cve-check manifests for %d machines (%s); pass "
                "--machine"
                % (
                    deploy_images,
                    len(scoped),
                    ", ".join(os.path.basename(d) for d in scoped),
                )
            )
        manifests = find_manifests(scoped[0]) if scoped else []

    pkgdata_dirs = sorted(
        d for d in glob.glob(os.path.join(tmpdir, "pkgdata", "*")) if os.path.isdir(d)
    )
    # PKGDATA_DIR is ${TMPDIR}/pkgdata/${MACHINE} and PKGDATA_DIR_SDK is
    # ${TMPDIR}/pkgdata/${SDK_SYS} (bitbake.conf); only the latter carries
    # "-linux", so anything else here is a machine.
    machine_dirs = [d for d in pkgdata_dirs if "-linux" not in os.path.basename(d)]
    if machine:
        # Without this the filter below can leave the SDK's pkgdata alone, and
        # a report named for the requested machine then describes nativesdk
        # packages: the no-packages guard sees a non-zero count and passes.
        if not any(os.path.basename(d) == machine for d in machine_dirs):
            raise ValueError(
                "no pkgdata for machine %r under %s (found: %s)"
                % (
                    machine,
                    os.path.join(tmpdir, "pkgdata"),
                    ", ".join(os.path.basename(d) for d in machine_dirs) or "none",
                )
            )
        pkgdata_dirs = [
            d
            for d in pkgdata_dirs
            if os.path.basename(d) == machine or "-linux" in os.path.basename(d)
        ]
    elif not machine_dirs:
        # Only the SDK's pkgdata is present, so every runtime package found
        # would be a nativesdk one and the report would describe the build host
        # under a machine's name. The no-packages guard cannot catch it: the
        # count is non-zero.
        raise ValueError(
            "%s holds no machine pkgdata, only the SDK's (%s); run a world "
            "build for the machine before reporting on it"
            % (
                os.path.join(tmpdir, "pkgdata"),
                ", ".join(os.path.basename(d) for d in pkgdata_dirs) or "none",
            )
        )
    elif len(machine_dirs) > 1:
        # Reading every machine unions their versions, and read_cve_data keeps
        # any manifest entry matching the union - so another machine's entry
        # passes as this one's rather than being dropped as stale, and no
        # counter records the substitution.
        raise ValueError(
            "%s holds pkgdata for %d machines (%s); pass --machine"
            % (
                os.path.join(tmpdir, "pkgdata"),
                len(machine_dirs),
                ", ".join(os.path.basename(d) for d in machine_dirs),
            )
        )
    pkgdata_dirs.sort(key=lambda d: "-linux" in os.path.basename(d))
    return manifests, pkgdata_dirs

def _mc_pairs(values, what, parser):
    """[(mc, rest)] of MC:VALUE arguments."""
    pairs = []
    for value in values:
        mc, sep, rest = value.partition(":")
        if not sep or not mc or not rest:
            parser.error("%s %r is not <multiconfig>:<value>" % (what, value))
        pairs.append((mc, rest))
    return pairs

def main():
    import argparse
    import sys

    # Spelled out rather than read from __doc__: the module opens with the SPDX
    # comment, and python -OO strips docstrings anyway.
    parser = argparse.ArgumentParser(
        description="Correlate runtime packages with sbom-cve-check results"
    )
    parser.add_argument("--tmpdir", help="build TMPDIR, e.g. build/tmp")
    parser.add_argument(
        "--manifest",
        action="append",
        default=[],
        help="sbom-cve-check manifest, or a directory holding %s files; "
        "repeatable. Overrides ${DEPLOY_DIR_IMAGE}" % MANIFEST_SUFFIX,
    )
    parser.add_argument(
        "--pkgdata-dir", action="append", default=[], help="override, repeatable"
    )
    parser.add_argument(
        "--alt-pkgdata-dir", action="append", default=[], metavar="MC:DIR",
        help="an alternate multiconfig's pkgdata, read after the others; its "
        "builds are <mc>:<recipe>. Repeatable")
    parser.add_argument(
        "--alt-recipe", action="append", default=[], metavar="MC:RECIPE",
        help="read only this recipe from that multiconfig's --alt-pkgdata-dir, "
        "as the build reads only AVOCADO_MULTIKERNEL_MC_RECIPES, in that "
        "variable's order. Repeatable; default every recipe")
    parser.add_argument(
        "--merge-by-multiconfig", action="store_true",
        help="rank alternate builds as a merge that publishes a multiconfig's "
        "whole tree at its first --alt-recipe entry (scarthgap), instead of "
        "pair by pair in --alt-recipe order (wrynose); this decides which "
        "build owns an RPM two trees built identically")
    parser.add_argument(
        "--coverage", metavar="FILE",
        help="the feed document's coverage record; the alternate builds it "
        "lists as not covered are unscanned, with its reason")
    parser.add_argument(
        "--compiled-source-recipe", action="append", default=None,
        help="a recipe in package data built with SPDX_INCLUDE_COMPILED_SOURCES, "
        "whose builds' not-applicable-config results from the compiled-source "
        "filter stand. Repeatable. Without it only kernels' do, and the report "
        "does not carry the flag")
    parser.add_argument(
        "--machine",
        help="MACHINE recorded in the report, and the ${DEPLOY_DIR}/images "
        "subdirectory the manifest is read from",
    )
    parser.add_argument(
        "--from-report",
        metavar="REPORT",
        help="a previous report of the same build, read instead of pkgdata: "
        "rebuild the report for a later scan of that build's SBOM. Needs "
        "--manifest; its machine, distro_version, status and summary carry over",
    )
    parser.add_argument(
        "--status",
        choices=REPORT_STATUSES,
        help="CVE status to list, default Unpatched (with --from-report, that "
        "report's). All lists every status, each CVE carrying "
        "its own, and then counts.unpatched_cves, patched_cves and ignored_cves "
        "count what is listed instead of what was left out",
    )
    parser.add_argument(
        "--no-summary", action="store_true", help="drop CVE description text"
    )
    parser.add_argument("-o", "--output", required=True)
    args = parser.parse_args()

    if args.from_report:
        return _main_from_report(parser, args)
    if args.status is None:
        args.status = "Unpatched"

    manifests, pkgdata_dirs = ([], [])
    if args.tmpdir:
        try:
            manifests, pkgdata_dirs = default_paths(args.tmpdir, args.machine)
        except ValueError as e:
            parser.error(str(e))
    if args.manifest:
        # A --manifest that names nothing readable has to fail here rather than
        # silently fall back to what --tmpdir found, which would report on a
        # different build than the one asked for.
        manifests = []
        for path in args.manifest:
            found = find_manifests(path)
            if not found:
                parser.error("no sbom-cve-check manifest at %s" % path)
            manifests.extend(found)
    pkgdata_dirs = args.pkgdata_dir or pkgdata_dirs
    alt_dirs = _mc_pairs(args.alt_pkgdata_dir, "--alt-pkgdata-dir", parser)
    alt_recipes = {}
    pairs = _mc_pairs(args.alt_recipe, "--alt-recipe", parser)
    for mc, recipe in pairs:
        alt_recipes.setdefault(mc, set()).add(recipe)
    merge_order = alt_merge_order(pairs, args.merge_by_multiconfig)
    unknown = sorted(set(alt_recipes) - {mc for mc, _path in alt_dirs})
    if unknown:
        parser.error("--alt-recipe names multiconfig(s) with no --alt-pkgdata-dir: %s"
                     % ", ".join(unknown))
    alt_trees = [(mc, path, alt_recipes.get(mc)) for mc, path in alt_dirs]
    for mc, path, recipes in alt_trees:
        problem = alt_tree_problem(path, recipes)
        if problem:
            parser.error("--alt-pkgdata-dir %s: %s" % (mc, problem))
    not_covered = None
    if args.coverage:
        try:
            with open(args.coverage) as f:
                not_covered = not_covered_builds(json.load(f))
        except (OSError, ValueError) as e:
            parser.error("--coverage %s: %s" % (args.coverage, e))

    if args.tmpdir and not manifests:
        # Distinct from the argument error below: the paths were worked out,
        # there is simply no scan to read. Saying "need --tmpdir" to someone who
        # passed --tmpdir sends them after the wrong problem.
        parser.error(
            "no %s under %s; nothing was scanned. Was the build run with the "
            "sbom-cve-check configuration, and has 'bitbake -c "
            "sbom_cve_check_recipe meta-world-recipe-sbom' run? Point "
            "--manifest at the export if DEPLOY_DIR is not under TMPDIR."
            % (WORLD_MANIFEST, os.path.join(args.tmpdir, "deploy", "images"))
        )

    if not manifests or not pkgdata_dirs:
        parser.error("need --tmpdir, or both --manifest and --pkgdata-dir")

    if os.path.isdir(args.output):
        parser.error("--output %s is a directory" % args.output)
    _refuse_output_over_inputs(parser, args.output,
                               manifests + ([args.coverage] if args.coverage else []))

    if os.path.exists(args.output):
        os.unlink(args.output)

    report, stats = build_report(
        manifests,
        pkgdata_dirs,
        machine=args.machine,
        status=args.status,
        summary=not args.no_summary,
        alt_trees=alt_trees,
        compiled_sources=args.compiled_source_recipe,
        not_covered=not_covered,
        merge_order=merge_order,
    )

    # Files found is not files read. A truncated manifest gets this far and
    # produces the zero-CVE document the checks above exist to prevent, with
    # only a counter line to tell them apart.
    if stats.cve_files_unreadable >= stats.cve_files:
        print(
            "all %d manifest(s) failed to parse (%s); nothing was scanned. An "
            "interrupted build leaves truncated files behind - rerun the scan, "
            "or delete the unreadable ones."
            % (stats.cve_files, ", ".join(manifests)),
            file=sys.stderr,
        )
        return 1

    if not stats.packages:
        print(
            "no runtime packages found in %s; nothing could be correlated. "
            "pkgdata is written by the packaging tasks, so a scan-only run "
            "never populates it - run 'bitbake world' first."
            % ", ".join(pkgdata_dirs),
            file=sys.stderr,
        )
        return 1

    return _write_and_summarize(report, stats, args.output, args.status)

def _refuse_output_over_inputs(parser, output, inputs):
    # The output is removed before anything can fail, and write_report() writes
    # output + ".tmp" first: neither may be one of the inputs.
    for out in (output, output + ".tmp"):
        if os.path.exists(out) and any(
                os.path.exists(p) and os.path.samefile(out, p) for p in inputs):
            parser.error("--output %s is one of the inputs" % out)

def _main_from_report(parser, args):
    import sys

    if (args.tmpdir or args.pkgdata_dir or args.alt_pkgdata_dir or args.alt_recipe
            or args.coverage or args.machine or args.compiled_source_recipe is not None):
        parser.error("--from-report replaces --tmpdir, --pkgdata-dir, "
                     "--alt-pkgdata-dir, --alt-recipe, --coverage, "
                     "--compiled-source-recipe and --machine")
    if not args.manifest:
        parser.error("--from-report needs --manifest")
    manifests = []
    for path in args.manifest:
        found = find_manifests(path)
        if not found:
            parser.error("no sbom-cve-check manifest at %s" % path)
        manifests.extend(found)
    if os.path.isdir(args.output):
        parser.error("--output %s is a directory" % args.output)
    _refuse_output_over_inputs(parser, args.output, [args.from_report] + manifests)

    if os.path.exists(args.output):
        os.unlink(args.output)

    try:
        with open(args.from_report) as f:
            anchor = json.load(f)
    except (OSError, ValueError) as e:
        print("cannot read %s: %s" % (args.from_report, e), file=sys.stderr)
        return 1

    try:
        report, stats = build_report_from_anchor(
            manifests, anchor, status=args.status,
            summary=False if args.no_summary else None, anchor_path=args.from_report)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1

    if stats.cve_files_unreadable >= stats.cve_files:
        print(
            "all %d manifest(s) failed to parse (%s); nothing was scanned."
            % (stats.cve_files, ", ".join(manifests)),
            file=sys.stderr,
        )
        return 1

    return _write_and_summarize(report, stats, args.output, report["status"])

def _write_and_summarize(report, stats, output, status):
    import sys

    write_report(report, output)

    counts = report["counts"]

    print(
        "%s: %d packages, %d builds, %d %s CVEs (%d builds, %d CVEs packaged)"
        % (
            output,
            counts["packages"],
            counts["builds"],
            counts["cves"],
            status.lower(),
            counts["packaged_builds"],
            counts["packaged_cves"],
        ),
        file=sys.stderr,
    )
    for key in (
        "alternate_builds",
        "unscanned_builds",
        "no_cve_record_builds",
        "not_covered_builds",
        "shared_package_builds",
        "stale_dropped",
        "package_collisions",
        "cve_files_unreadable",
        "entries_unreadable",
        "pkgdata_unreadable",
        "unpatched_cves",
        "ignored_cves",
        "patched_cves",
        "unknown_status_cves",
        "unverified_compiled_source_cves",
    ):
        if stats.get(key):
            print("  %s: %d" % (key, stats[key]), file=sys.stderr)

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
