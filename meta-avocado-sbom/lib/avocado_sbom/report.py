# SPDX-License-Identifier: Apache-2.0

import datetime
import glob
import hashlib
import json
import os

class Stats(dict):
    _NAMES = (
        "packages",
        "recipes",
        "cves",
        "packaged_recipes",
        "packaged_cves",
        "cve_files",
        "cve_files_unreadable",
        "entries_unreadable",
        "pkgdata_unreadable",
        "package_collisions",
        "stale_dropped",
        "unscanned_recipes",
        "no_cve_record_recipes",
        "alt_recipes",
        "alt_cves",
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
    """(package name, recipe, package version, version keys) for each package
    one pkgdata directory names. The keys are PV and plain PKGV, the versions a
    manifest entry is matched against."""
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
        yield name, recipe, version, keys

def _add_package(packages, name, recipe, version, origin, stats):
    """Whether this directory won the name: the first one to claim it does."""
    if name in packages:
        if (packages[name]["recipe"] != recipe or
            packages[name]["version"] != version):
            stats.package_collisions += 1
        return False
    packages[name] = {
        "recipe": recipe,
        "version": version,
        "origin": origin,
    }
    return True

def read_pkgdata(pkgdata_dirs, stats):
    packages = {}
    recipe_versions = {}

    for pkgdata_dir in pkgdata_dirs:
        origin = os.path.basename(pkgdata_dir.rstrip("/"))
        for name, recipe, version, keys in _pkgdata_entries(pkgdata_dir, stats):
            recipe_versions.setdefault(recipe, set()).update(keys)
            _add_package(packages, name, recipe, version, origin, stats)

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
    found = {recipe for _n, recipe, _v, _k in _pkgdata_entries(pkgdata_dir, Stats())}
    if recipes is None:
        return None if found else "%s holds no readable package data" % pkgdata_dir
    missing = sorted(set(recipes) - found)
    if missing:
        return "%s holds no package of %s" % (pkgdata_dir, ", ".join(missing))
    return None

def read_alt_pkgdata(alt_trees, packages, recipe_versions, stats):
    """Add an alternate multiconfig's packages to what read_pkgdata returned.

    alt_trees is a list of (pkgdata_dir, recipes): each multiconfig's pkgdata,
    and the recipes of it that reach the feed (AVOCADO_MULTIKERNEL_MC_RECIPES),
    the only ones read. None reads every recipe.

    A recipe the default multiconfig also built is the same recipe at a second
    version, the 6.6 kernel beside the 6.12 one. Those versions are returned
    as {recipe: {version: [package names]}}: a manifest entry at one of them
    becomes an alt_versions record, and the names are the packages built from
    it. A name the default multiconfig already claimed ("kernel", "kernel-dev")
    stays the default's, so it is in no list. A recipe only an alternate
    multiconfig built is an ordinary one, read like the default's.
    """
    alt = {}
    # The versions the first tree to build each recipe built it at.
    primary = {r: set(v) for r, v in recipe_versions.items()}

    for pkgdata_dir, recipes in alt_trees:
        origin = os.path.basename(pkgdata_dir.rstrip("/"))
        known = set(primary)
        for name, recipe, version, keys in _pkgdata_entries(pkgdata_dir, stats):
            if recipes is not None and recipe not in recipes:
                continue
            recipe_versions.setdefault(recipe, set()).update(keys)
            won = _add_package(packages, name, recipe, version, origin, stats)
            if recipe not in known:
                primary.setdefault(recipe, set()).update(keys)
                continue
            for key in keys - primary[recipe]:
                names = alt.setdefault(recipe, {}).setdefault(key, set())
                if won:
                    names.add(name)

    stats.packages = len(packages)
    return {r: {v: sorted(n) for v, n in by_version.items()}
            for r, by_version in alt.items()}

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
    """What the manifests say about each recipe beyond its CVEs.

    seen       recipes with at least one readable entry at a version this
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

def _record(version, packaged):
    return {"version": version, "packaged": packaged, "cves": []}

# What sbom-cve-check 1.4.0 writes for a CVE its compiled-source filter drops:
# the record names the files the fix touches and none is in the build's list of
# sources (analysis/compiled_sources.py). A recipe's own CVE_STATUS can carry the
# same detail, with its own reason as the description, so both are matched.
COMPILED_SOURCE_DETAIL = "not-applicable-config"
COMPILED_SOURCE_DESCRIPTION = "vulnerable_code_not_present: Source code not compiled by config"
# The CPE product of a kernel. The scanner uses a kernel's list only when it
# names files every kernel build compiles, so only a real source walk passes.
KERNEL_PRODUCT = "linux_kernel"

def trusts_compiled_sources(name, products, compiled_sources):
    """Whether the compiled-source filter's result stands for this entry.

    The scanner reads the build's source files as the recipe's compiled sources.
    A recipe built with SPDX_INCLUDE_COMPILED_SOURCES lists what its build
    compiled; any other lists only what it fetched, so a CVE in a file it never
    fetched by name reads as not compiled. compiled_sources is the set of
    recipes built with the setting, or None when the report does not know it
    (a report written before it carried the list): then only kernels are
    trusted, which is every recipe the setting was ever made for, and for which
    the scanner rejects a list that did not come from a source walk.

    do_cve_report reads the setting from its own datastore, which sees the
    same :pn- lines a recipe's parse does. A recipe that turns it off in its
    own parse (linux-yocto with module-signing) writes no source walk, and as
    a kernel its fetched-only list is rejected by the scanner anyway.
    """
    if compiled_sources is None:
        return KERNEL_PRODUCT in products
    return name in compiled_sources

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

def read_cve_data(manifests, recipe_versions, stats, status="Unpatched", summary=True,
                  alt_versions=None, compiled_sources=None):
    """The recipe -> CVEs map, and the Coverage the manifests give.

    alt_versions is {recipe: versions} for the versions only an alternate
    multiconfig built (read_alt_pkgdata). An entry at one of them is filed as an
    alt_versions record of its recipe, never merged into the record of the
    version the default multiconfig built.

    compiled_sources is the set of recipes whose compiled-source list the
    filter may trust, or None (see trusts_compiled_sources). Any other recipe's
    CVE the filter dropped is listed as Unpatched with no detail (the filter replaced
    the scanner's version result, so which one it was is unknown), with what the
    scanner said under "scanner".
    """
    fields = (
        CVE_FIELDS
        if summary
        else tuple(f for f in CVE_FIELDS if f not in CVE_SUMMARY_FIELDS)
    )
    listed = set(CVE_STATUSES) if status == STATUS_ALL else {status}
    alt_versions = alt_versions or {}
    coverage = Coverage()
    # {recipe: {None or alt version: record}}, None being the default
    # multiconfig's. Insertion order is manifest order.
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
            # seen: a recipe with no other entry is unscanned.
            known = recipe_versions.get(name)
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

            alt = version if version in alt_versions.get(name, ()) else None
            by_version = records.setdefault(name, {})
            record = by_version.get(alt)
            if record is None:
                record = by_version[alt] = _record(version, name in recipe_versions)
            # Two entries for one record: a directory of manifests, where a
            # per-image export sits beside the world one, or a multilib
            # variant. Merge by CVE id rather than overwrite, or the counts
            # would keep the CVEs the report body just lost. The version first
            # recorded stands.
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

    recipes = {}
    for name, by_version in records.items():
        # The default multiconfig's record, or the first alternate one when the
        # default listed nothing: a placeholder at the default version with no
        # CVEs would bind that kernel's packages as clean.
        main = by_version.pop(None, None)
        alts = list(by_version.values())
        if main is None:
            main = alts.pop(0)
        if alts:
            main["alt_versions"] = alts
        recipes[name] = main

    for record in recipes.values():
        stats.cves += len(record["cves"])
        if record["packaged"]:
            stats.packaged_recipes += 1
            stats.packaged_cves += len(record["cves"])
        alts = record.get("alt_versions", [])
        if alts:
            stats.alt_recipes += 1
            stats.alt_cves += sum(len(a["cves"]) for a in alts)
        for each in [record] + alts:
            for cve in each["cves"]:
                if "scanner" in cve:
                    stats.unverified_compiled_source_cves += 1
                if status == STATUS_ALL:
                    # What the report lists, counted off the report, so a CVE
                    # two entries share is counted once: unpatched_cves +
                    # patched_cves + ignored_cves equals cves + alt_cves.
                    stats[_FILTERED_COUNTER[cve["status"]]] += 1

    stats.recipes = len(recipes)
    return recipes, coverage

def stamp_recipe_versions(packages, recipes, alt_packages):
    """Give each package built at a version "recipes" has a record of that
    version as "recipe_version".

    Both kernels' packages name one recipe, so the recipe alone cannot join a
    6.6 module to the 6.6 record. A package of a version with no record gets
    no stamp: a consumer then knows no record describes it, rather than reading
    the other version's CVEs as its own.
    """
    by_recipe = {}
    for name, pkg in packages.items():
        pkg.pop("recipe_version", None)
        by_recipe.setdefault(pkg["recipe"], []).append(name)

    for recipe, record in recipes.items():
        alt = alt_packages.get(recipe, {})
        alt_names = {n for names in alt.values() for n in names}
        for each in [record] + record.get("alt_versions", []):
            version = each["version"]
            if version in alt:
                names = alt[version]
            else:
                names = [n for n in by_recipe.get(recipe, ()) if n not in alt_names]
            for name in names:
                packages[name]["recipe_version"] = version

REPORT_VERSION = "1"

def build_report(manifests, pkgdata_dirs, machine=None, status="Unpatched", summary=True,
                 alt_trees=(), compiled_sources=None):
    """alt_trees are the alternate multiconfigs' (pkgdata_dir, recipes), read
    after pkgdata_dirs; see read_alt_pkgdata. compiled_sources names the
    recipes built with SPDX_INCLUDE_COMPILED_SOURCES, or is a function telling
    whether a recipe was, asked for every recipe in package data, or is None
    when that is not known; see trusts_compiled_sources. The report carries
    the set."""
    if status not in REPORT_STATUSES:
        raise ValueError(
            "unknown CVE status %r; expected one of %s"
            % (status, ", ".join(REPORT_STATUSES))
        )

    stats = Stats()
    packages, recipe_versions = read_pkgdata(pkgdata_dirs, stats)
    alt_packages = read_alt_pkgdata(alt_trees, packages, recipe_versions, stats)
    if callable(compiled_sources):
        compiled_sources = {r for r in recipe_versions if compiled_sources(r)}
    elif compiled_sources is not None:
        compiled_sources = set(compiled_sources)
    return _assemble(manifests, packages, recipe_versions, alt_packages, stats,
                     machine, status, summary, compiled_sources)

def packages_digest(packages):
    digest = hashlib.sha256()
    for name in sorted(packages):
        pkg = packages[name]
        digest.update(
            ("%s\t%s\t%s\n" % (name, pkg["recipe"], pkg["version"])).encode()
        )
    return "sha256:" + digest.hexdigest()

def _anchor_error(path, what):
    return ValueError("%s: %s" % (path, what))

def _anchor_parts(anchor, path):
    """The pkgdata a build's report carries: packages, recipe_versions and the
    two pkgdata counters, checked for the shape build_report writes."""
    if not isinstance(anchor, dict):
        raise _anchor_error(path, "not a CVE report object")
    if anchor.get("version") != REPORT_VERSION:
        raise _anchor_error(
            path, "report version %r, expected %r"
            % (anchor.get("version"), REPORT_VERSION))
    if "recipe_versions" not in anchor:
        raise _anchor_error(
            path, "no recipe_versions; the build was scanned before the report "
            "carried them, so it cannot be rebuilt from a later scan")

    packages = anchor.get("packages")
    if not isinstance(packages, dict) or not packages or not all(
            isinstance(n, str) and isinstance(p, dict)
            and all(isinstance(p.get(k), str) for k in ("recipe", "version", "origin"))
            for n, p in packages.items()):
        raise _anchor_error(path, "packages is missing, empty or malformed")

    versions = anchor["recipe_versions"]
    if not isinstance(versions, dict) or not all(
            isinstance(v, list) and v and all(isinstance(x, str) and x for x in v)
            for v in versions.values()):
        raise _anchor_error(path, "recipe_versions is malformed")

    for key in ("machine", "distro_version"):
        value = anchor.get(key)
        if key in anchor and not (isinstance(value, str) and value):
            raise _anchor_error(path, "%s is malformed" % key)

    counts = anchor.get("counts")
    if not isinstance(counts, dict):
        raise _anchor_error(path, "counts is missing")
    carried = {}
    for key in ("pkgdata_unreadable", "package_collisions"):
        value = counts.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise _anchor_error(path, "counts.%s is missing or malformed" % key)
        carried[key] = value

    if anchor.get("packages_digest") != packages_digest(packages):
        raise _anchor_error(path, "packages do not match packages_digest")
    # recipe_version is recomputed from this scan's records.
    packages_in = packages
    packages = {n: {k: p[k] for k in ("recipe", "version", "origin")}
                for n, p in packages_in.items()}

    if "alt_packages" in anchor:
        alt_packages = anchor["alt_packages"]
        if not isinstance(alt_packages, dict) or not all(
                isinstance(by_version, dict) and all(
                    isinstance(v, str) and v and isinstance(names, list) and all(
                        isinstance(n, str) and packages.get(n, {}).get("recipe") == r
                        for n in names)
                    for v, names in by_version.items())
                for r, by_version in alt_packages.items()):
            raise _anchor_error(path, "alt_packages is malformed")
    else:
        alt_packages = _alt_packages_from_records(anchor, packages_in)

    # Absent from a report written before it carried the list: then only kernels
    # keep the filter's result, the rule that report's build was made for.
    compiled_sources = None
    if "compiled_source_recipes" in anchor:
        compiled_sources = anchor["compiled_source_recipes"]
        if not isinstance(compiled_sources, list) or not all(
                isinstance(r, str) and r for r in compiled_sources):
            raise _anchor_error(path, "compiled_source_recipes is malformed")
        compiled_sources = set(compiled_sources)

    # read_pkgdata keys every recipe that wrote a pkgdata file, and the report
    # drops the ones with no version. Restore those for the "packaged" test. One
    # that also lost every package name to an earlier directory cannot be restored;
    # runtime-reverse files always carry PV, so no real build has one.
    recipe_versions = {name: set(v) for name, v in versions.items()}
    for pkg in packages.values():
        recipe_versions.setdefault(pkg["recipe"], set())
    return packages, recipe_versions, alt_packages, carried, compiled_sources

def _alt_packages_from_records(anchor, packages):
    """alt_packages for a report written before it carried them.

    A report that already filed a second version under alt_versions (scarthgap's
    cve-check generator) stamped its packages with that version, which is the
    same split. Without it every package of the recipe would be read as the
    default version's, and a rescan would file the 6.6 modules under the 6.12
    kernel's CVEs.
    """
    recipes = anchor.get("recipes")
    if not isinstance(recipes, dict):
        return {}
    alt = {}
    # Every recorded version, even one whose packages all lost their names to
    # the default's, or its CVEs would merge into the default record.
    for recipe, record in recipes.items():
        alts = record.get("alt_versions") if isinstance(record, dict) else None
        if isinstance(alts, list):
            for a in alts:
                if isinstance(a, dict) and isinstance(a.get("version"), str) and a["version"]:
                    alt.setdefault(recipe, {}).setdefault(a["version"], [])
    for name, pkg in sorted(packages.items()):
        record = recipes.get(pkg["recipe"])
        alts = record.get("alt_versions") if isinstance(record, dict) else None
        version = pkg.get("recipe_version")
        if isinstance(alts, list) and any(
                isinstance(a, dict) and a.get("version") == version for a in alts):
            alt.setdefault(pkg["recipe"], {}).setdefault(version, []).append(name)
    return alt

def build_report_from_anchor(manifests, anchor, status=None, summary=True,
                             anchor_path="anchor report"):
    """The report build_report would have written for `manifests`, from a
    previous report of the same build instead of its pkgdata.

    `anchor` is that report as parsed. It needs recipe_versions, so a report
    written before they were added is refused. machine, distro_version and,
    unless `status` is given, the status are taken from it.
    """
    packages, recipe_versions, alt_packages, carried, compiled_sources = _anchor_parts(
        anchor, anchor_path)
    if status is None:
        status = anchor.get("status")
    if status not in REPORT_STATUSES:
        raise ValueError(
            "unknown CVE status %r; expected one of %s"
            % (status, ", ".join(REPORT_STATUSES))
        )

    stats = Stats()
    stats.packages = len(packages)
    for key, value in carried.items():
        stats[key] = value
    report, stats = _assemble(manifests, packages, recipe_versions, alt_packages,
                              stats, anchor.get("machine"), status, summary,
                              compiled_sources)
    if anchor.get("distro_version"):
        report["distro_version"] = anchor["distro_version"]
    return report, stats

def _assemble(manifests, packages, recipe_versions, alt_packages, stats, machine,
              status, summary, compiled_sources=None):
    recipes, coverage = read_cve_data(
        manifests, recipe_versions, stats, status=status, summary=summary,
        alt_versions={r: set(v) for r, v in alt_packages.items()},
        compiled_sources=compiled_sources,
    )
    stamp_recipe_versions(packages, recipes, alt_packages)

    # Every recipe that shipped a package lands in exactly one of: "recipes",
    # no_cve_record_recipes, unscanned_recipes, or none of them, which a
    # consumer reads as scanned and clean. So none is kept for a recipe whose
    # entries matched CVEs at a status this report knows and listed none of
    # them at its status. Anything short of that is unscanned: no entry, only
    # entries at a version this build does not have, only unreadable ones, or
    # only issues of an unknown status.
    shipped = {p["recipe"] for p in packages.values()}
    no_record = sorted(shipped & coverage.no_record)
    unscanned = sorted(shipped - coverage.no_record - coverage.assessed - set(recipes))
    stats.no_cve_record_recipes = len(no_record)
    stats.unscanned_recipes = len(unscanned)

    report = {
        "version": REPORT_VERSION,
        "generated": datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "packages_digest": packages_digest(packages),
        "status": status,
        "counts": {
            "recipes": len(recipes),
            "cves": stats.cves,
            "packaged_recipes": stats.packaged_recipes,
            "packaged_cves": stats.packaged_cves,
            "packages": len(packages),
            "cve_files": stats.cve_files,
            "stale_dropped": stats.stale_dropped,
            "unscanned_recipes": stats.unscanned_recipes,
            "no_cve_record_recipes": stats.no_cve_record_recipes,
            "alt_recipes": stats.alt_recipes,
            "alt_cves": stats.alt_cves,
            "cve_files_unreadable": stats.cve_files_unreadable,
            "entries_unreadable": stats.entries_unreadable,
            "pkgdata_unreadable": stats.pkgdata_unreadable,
            "package_collisions": stats.package_collisions,
            "unpatched_cves": stats.unpatched_cves,
            "ignored_cves": stats.ignored_cves,
            "patched_cves": stats.patched_cves,
            "unknown_status_cves": stats.unknown_status_cves,
            "unverified_compiled_source_cves": stats.unverified_compiled_source_cves,
        },
        "recipes": recipes,
        "packages": packages,
        "unscanned_recipes": unscanned,
        "no_cve_record_recipes": no_record,
        # Which packages an alternate multiconfig built at a second version of
        # a recipe, for a rescan to file them the same way: packages carry
        # PKGV-PKGR, which does not say which multiconfig built them.
        "alt_packages": {
            name: {v: list(names) for v, names in sorted(by_version.items())}
            for name, by_version in sorted(alt_packages.items())
        },
        # What read_cve_data matched entries against. A rescan without the
        # build tree needs it: packages carry PKGV-PKGR, which no entry does.
        "recipe_versions": {
            name: sorted(versions)
            for name, versions in sorted(recipe_versions.items())
            if versions
        },
    }
    if compiled_sources is not None:
        # The recipes whose compiled-source filter results stand, for a rescan
        # to apply the same rule. Without it only kernels' do.
        report["compiled_source_recipes"] = sorted(compiled_sources)
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
        "--alt-pkgdata-dir", action="append", default=[],
        help="an alternate multiconfig's pkgdata, read after the others; a "
        "recipe it builds at a second version gets alt_versions records. "
        "Repeatable")
    parser.add_argument(
        "--alt-recipe", action="append", default=[],
        help="read only this recipe from every --alt-pkgdata-dir, as the build "
        "reads only AVOCADO_MULTIKERNEL_MC_RECIPES. Repeatable; default every "
        "recipe")
    parser.add_argument(
        "--compiled-source-recipe", action="append", default=None,
        help="a recipe built with SPDX_INCLUDE_COMPILED_SOURCES, whose "
        "not-applicable-config results from the compiled-source filter stand. "
        "Repeatable. Without it only kernels' do, and the report does not "
        "carry the list")
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
        "--manifest; its machine, distro_version and status carry over",
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
    for path in args.alt_pkgdata_dir:
        problem = alt_tree_problem(path, set(args.alt_recipe) or None)
        if problem:
            parser.error("--alt-pkgdata-dir: %s" % problem)

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

    if os.path.exists(args.output):
        os.unlink(args.output)

    report, stats = build_report(
        manifests,
        pkgdata_dirs,
        machine=args.machine,
        status=args.status,
        summary=not args.no_summary,
        alt_trees=[(path, set(args.alt_recipe) or None)
                   for path in args.alt_pkgdata_dir],
        compiled_sources=args.compiled_source_recipe,
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

def _main_from_report(parser, args):
    import sys

    if (args.tmpdir or args.pkgdata_dir or args.alt_pkgdata_dir or args.machine
            or args.compiled_source_recipe is not None):
        parser.error("--from-report replaces --tmpdir, --pkgdata-dir, "
                     "--alt-pkgdata-dir, --compiled-source-recipe and --machine")
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
    # The output is removed before anything can fail, and write_report() writes
    # output + ".tmp" first: neither may be one of the inputs.
    for out in (args.output, args.output + ".tmp"):
        if os.path.exists(out) and any(
                os.path.exists(p) and os.path.samefile(out, p)
                for p in [args.from_report] + manifests):
            parser.error("--output %s is one of the inputs" % out)

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
            summary=not args.no_summary, anchor_path=args.from_report)
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
        "%s: %d packages, %d recipes, %d %s CVEs (%d recipes, %d CVEs packaged)"
        % (
            output,
            counts["packages"],
            counts["recipes"],
            counts["cves"],
            status.lower(),
            counts["packaged_recipes"],
            counts["packaged_cves"],
        ),
        file=sys.stderr,
    )
    for key in (
        "unscanned_recipes",
        "no_cve_record_recipes",
        "alt_recipes",
        "alt_cves",
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
