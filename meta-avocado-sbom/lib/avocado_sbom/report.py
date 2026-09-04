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
        "device_recipes",
        "device_cves",
        "cve_files",
        "cve_files_unreadable",
        "pkgdata_unreadable",
        "package_collisions",
        "stale_dropped",
        "unscanned_recipes",
        "no_cve_record_recipes",
        "unpatched_cves",
        "ignored_cves",
        "patched_cves",
        "unknown_status_cves",
        "manifests_read",
        "alt_recipes",
        "alt_cves",
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
                if sep and key in ("PN", "PV", "PKGV", "PKGR"):
                    fields[key] = value.strip()
    except OSError:
        return {}
    return fields

def read_pkgdata(pkgdata_dirs, stats):
    """Read the runtime package map.

    The third return splits a recipe's package names by version, so a recipe
    built twice in one build - a multi-kernel machine's kernel - is scoped on
    the packages of the version being scoped rather than on both versions'.
    Keyed on PV and PKGV alike, because a cve-check entry's version is one or
    the other.

    The fourth says which version each package name was built at, for the
    directory that won the name. Both kernels package "kernel", "kernel-dbg"
    and "kernel-dev", so the third alone cannot tell whose an installed name
    is.
    """
    packages = {}
    recipe_versions = {}
    recipe_version_packages = {}
    package_versions = {}

    for pkgdata_dir in pkgdata_dirs:
        origin = os.path.basename(pkgdata_dir.rstrip("/"))
        reverse_dir = os.path.join(pkgdata_dir, "runtime-reverse")
        if not os.path.isdir(reverse_dir):
            continue

        for path in sorted(glob.glob(os.path.join(reverse_dir, "*"))):
            name = os.path.basename(path)
            fields = _read_pkgdata_fields(path)
            recipe = fields.get("PN")
            if not recipe:
                stats.pkgdata_unreadable += 1
                continue

            version = _join_version(fields.get("PKGV"), fields.get("PKGR"))
            keys = {v for v in (fields.get("PV"), fields.get("PKGV")) if v}
            recipe_versions.setdefault(recipe, set()).update(keys)
            by_version = recipe_version_packages.setdefault(recipe, {})
            for v in keys:
                by_version.setdefault(v, []).append(name)

            if name in packages:
                if (packages[name]["recipe"] != recipe or
                    packages[name]["version"] != version):
                    stats.package_collisions += 1
                continue

            package_versions[name] = keys
            packages[name] = {
                "recipe": recipe,
                "version": version,
                "origin": origin,
            }

    stats.packages = len(packages)
    return packages, recipe_versions, recipe_version_packages, package_versions

def read_manifests(manifest_paths, stats):
    """Package names installed by the given image manifests.

    A manifest line is "PKG ARCH VERSION". An absent one is not an error - see
    _scope for why the report degrades rather than fails.
    """
    installed = set()

    for path in manifest_paths:
        try:
            with open(path, errors="ignore") as f:
                lines = f.read().splitlines()
        except OSError:
            continue

        names = {fields[0] for fields in (line.split() for line in lines) if fields}
        if not names:
            # Truncated: counting it would report the image as scoped by it.
            continue
        installed.update(names)
        stats.manifests_read += 1

    return installed

# Most privileged first. A label on every finding, never a filter on the
# report - the README's "Scope" section has why.
SCOPES = ("boot-chain", "base-runtime", "feed", "build-only")

# Naming is the only signal the report's inputs carry; the real one is whether
# the recipe inherits deploy, which needs a per-recipe datastore the standalone
# path lacks. Checked against all 94 package-less recipes on a qemuarm64 world
# build - the -source and -initial families are there because gcc-source-<PV>
# and libgcc-initial matched none of the obvious suffixes.
def _is_host_tooling(recipe):
    return (
        recipe.endswith(("-native", "-cross", "-crosssdk", "-initial", "-source"))
        or "-cross-" in recipe
        or "-source-" in recipe
    )

def _scope(recipe, package_names, installed, boot_chain):
    """Which surface a recipe occupies.

    Boot chain is matched by name, not package membership: u-boot and
    trusted-firmware-a reach the device through avocado-img-bootfiles, which
    scrapes DEPLOY_DIR_IMAGE, so no manifest names them.

    An installed package beats that name. firmware-imx and tegra-firmware are
    boot chain and also ship packages the rootfs installs; matching the name
    first would move them out of base-runtime, the set a consumer filters on to
    ask what is in the rootfs.

    "build-only" is the only value asserting a recipe is NOT on the device, so
    it is earned rather than defaulted to. Read no manifest and everything
    packaged reads "feed" - over-reporting the device, which is the safe way to
    be wrong.
    """
    # Before package membership, unlike the rest of host tooling: PKGDATA_DIR_SDK
    # packages nativesdk recipes, so they are packaged and would read "feed" -
    # installable on a device, which is what the prefix rules out.
    if recipe.startswith("nativesdk-"):
        return "build-only"
    if any(name in installed for name in package_names):
        return "base-runtime"
    if recipe in boot_chain:
        return "boot-chain"
    if package_names:
        return "feed"
    if _is_host_tooling(recipe):
        return "build-only"
    # Deploy-only target recipe - imx-atf, imx-boot, firmware-*, a u-boot with
    # PACKAGES = "". The README's "packaged" section says their CVEs are real
    # and on the device, so build-only would hide them.
    return "boot-chain"

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
# The whole vocabulary cve-check emits: conf/cve-check-map.conf maps every
# CVE_STATUS keyword onto one of these three. Filtering on anything else would
# match no issue at all and produce an empty, CVE-free-looking report.
CVE_STATUSES = ("Unpatched", "Patched", "Ignored")

# Kept in step with the recipe's AVOCADO_CVE_REPORT_STATUS: a run prunes the
# documents its statuses do not cover, so two defaults that disagreed would
# delete each other's output.
DEFAULT_STATUSES = ("Unpatched", "Patched")

# The whole vocabulary of the "evidence" field. Mirrored by the schema's enum,
# which test_verify pins to this tuple - the two drifting apart is how a
# consumer ends up filtering on a value nothing emits.
CVE_EVIDENCE = ("cve-status", "patch-file", "cve-check")

_FILTERED_COUNTER = {
    "Unpatched": "unpatched_cves",
    "Patched": "patched_cves",
    "Ignored": "ignored_cves",
}

def _evidence(issue, status, backported):
    """Who decided this issue's status. See the README's "Evidence" section for
    why the distinction is the point of the patched half.

    backported is the recipe's set of CVEs fixed by a patch it applies, from
    avocado-cve-backports.bbclass. Empty when the class is not inherited, and
    the patch-file half then folds back into "cve-check" - a build that says
    less rather than one that guesses.
    """
    if issue.get("detail"):
        return CVE_EVIDENCE[0]
    if status != "Patched":
        return None
    return CVE_EVIDENCE[1] if issue.get("id") in backported else CVE_EVIDENCE[2]

def filtered_counts(counts):
    """The counters naming what a document left out, as "N status" phrases.

    Shared so the recipe's build log and the standalone run cannot drift into
    describing the same numbers differently.
    """
    return ", ".join(
        "%d %s" % (counts[k], k[:-len("_cves")].replace("_", " "))
        for k in ("unpatched_cves", "patched_cves", "ignored_cves",
                  "unknown_status_cves")
        if counts.get(k)
    )

def parse_statuses(value):
    """The requested statuses, in the order given and deduplicated.

    "Unpatched Unpatched" asks for one document; without this it would write
    the same path twice. Raises ValueError naming every status cve-check never
    emits, so a caller can report them all at once.
    """
    statuses = list(dict.fromkeys((value or "").split()))
    if not statuses:
        raise ValueError(
            "no status given; expected one or more of %s"
            % ", ".join(CVE_STATUSES)
        )
    unknown = [st for st in statuses if st not in CVE_STATUSES]
    if unknown:
        raise ValueError(
            "%s: not a status cve-check emits; expected one or more of %s"
            % (", ".join(repr(u) for u in unknown), ", ".join(CVE_STATUSES))
        )
    return statuses

def _strip_pe(version):
    """Drop the EXTENDPE prefix cve-check puts in front of PV, as in
    "1_1.20.0".
    """
    epoch, sep, rest = version.partition("_")
    if sep and epoch.isdigit():
        return rest
    return version

def _has_cve_record(entry):
    """Whether the NVD holds any CVE record for this entry's products.

    False is a scan result, not the absence of one: cve-check looked the
    product up and the database had nothing under that name. Do not use it to
    decide whether a recipe was scanned - presence of the entry decides that.
    """
    products = entry.get("products")
    if not isinstance(products, list) or not products:
        return True
    return any(
        not isinstance(p, dict) or p.get("cvesInRecord") != "No" for p in products
    )

def read_cve_data(cve_dir, recipe_versions, stats, status="Unpatched",
                  summary=True, backports=None, alt_cve_dirs=()):
    """Join the per-recipe cve-check results into one recipe -> CVEs map.

    alt_cve_dirs are the per-multiconfig subdirectories
    avocado-multikernel.bbclass merges into CVE_CHECK_DIR. A recipe they hold
    at a second version becomes an alt_versions record rather than being merged
    into the entry, so the shipped kernel's CVE list stays the shipped
    kernel's.

    Two versions in cve_dir itself are still merged by id: CVE_CHECK_DIR is
    never pruned, so a result left by an earlier build at an older PV is
    indistinguishable from a current one. Only a subdirectory says a second
    multiconfig built this now.
    """
    fields = (
        CVE_FIELDS
        if summary
        else tuple(f for f in CVE_FIELDS if f not in CVE_SUMMARY_FIELDS)
    )
    recipes = {}
    scanned = set()
    with_record = set()
    # The version the default multiconfig built each recipe at, recorded
    # whether or not its entry carried a CVE at this status. An entry is what
    # says which version ships, and one with no issue at this status writes
    # none - so recipes alone cannot answer that for the alt merge below.
    default_versions = {}
    backports = backports or {}

    paths = [(p, False)
             for p in sorted(glob.glob(os.path.join(cve_dir, "*_cve.json")))]
    for alt_dir in alt_cve_dirs or ():
        paths += [(p, True)
                  for p in sorted(glob.glob(os.path.join(alt_dir, "*_cve.json")))]
    stats.cve_files = len(paths)

    for path, is_alt in paths:
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

        for entry in entries:
            name = entry.get("name")
            version = entry.get("version", "")
            if not isinstance(name, str) or not name or not isinstance(version, str):
                stats.cve_files_unreadable += 1
                break

            # Presence of an entry is what separates a recipe something
            # examined from one nothing looked at, so this is recorded before
            # the stale-version drop below: those recipes were scanned, just at
            # a version this build does not have. cvesInRecord says something
            # narrower - the NVD holds no record for the product - which is
            # tracked separately and must not be read as unscanned.
            scanned.add(name)
            if _has_cve_record(entry):
                with_record.add(name)

            known = recipe_versions.get(name)
            stripped = _strip_pe(version)
            if not known:
                version = stripped
            elif version not in known:
                if stripped not in known:
                    stats.stale_dropped += 1
                    continue
                version = stripped

            if not is_alt:
                default_versions.setdefault(name, version)

            raw_issues = entry.get("issue", [])
            if not isinstance(raw_issues, list) or not all(
                isinstance(i, dict) for i in raw_issues):
                stats.cve_files_unreadable += 1
                break

            issues = []
            seen_here = set()
            for issue in raw_issues:
                issue_status = issue.get("status")
                if issue_status == status:
                    # An id repeated inside one entry is one CVE, the same as
                    # one repeated across two entries - see the merge below.
                    # Dropping it here covers both, and covers the first entry
                    # for a recipe, which the merge never sees.
                    if issue.get("id") in seen_here:
                        continue
                    seen_here.add(issue.get("id"))
                    kept = {k: issue[k] for k in fields if k in issue}
                    # Read off the raw issue, not off kept: --no-summary drops
                    # prose, never what decided a status.
                    evidence = _evidence(issue, status, backports.get(name, ()))
                    if evidence:
                        kept["evidence"] = evidence
                    issues.append(kept)
                    continue

                counter = _FILTERED_COUNTER.get(issue_status)
                if counter:
                    stats[counter] += 1
                else:
                    stats.unknown_status_cves += 1

            if not issues:
                continue

            packaged = name in recipe_versions
            existing = recipes.get(name)
            default_version = default_versions.get(name)
            if is_alt and default_version is not None and version != default_version:
                # Merging by id would file this version's CVEs under the other
                # version's number.
                #
                # packaged is the entry's: the stale drop above has already
                # established that pkgdata knows this version. scope is not -
                # build_report fills it from this version's own packages.
                if existing is None:
                    # The default multiconfig built this recipe but carried no
                    # CVE at this status, so nothing recorded it. Its version is
                    # still the one that ships, so the entry is created at that
                    # version and the alt hangs off it rather than replacing it.
                    existing = recipes[name] = {
                        "version": default_version,
                        "packaged": packaged,
                        "cves": [],
                    }
                    if packaged:
                        stats.packaged_recipes += 1
                alt = next(
                    (a for a in existing.setdefault("alt_versions", [])
                     if a["version"] == version),
                    None,
                )
                if alt is None:
                    if not existing["alt_versions"]:
                        stats.alt_recipes += 1
                    alt = {"version": version, "packaged": packaged, "cves": []}
                    existing["alt_versions"].append(alt)
                seen_ids = {c.get("id") for c in alt["cves"]}
                added = [c for c in issues if c.get("id") not in seen_ids]
                alt["cves"].extend(added)
                stats.alt_cves += len(added)
                continue

            if existing is not None:
                # Two entries for one recipe - two files naming it, or two
                # entries in one file. Overwriting would leave the counters
                # holding the replaced entry's CVEs, and a report whose counts
                # exceed what it carries fails its own check as malformed,
                # which no setting overrides. Merge instead, by id: the same
                # CVE reported twice is one CVE.
                #
                # The version already recorded stands, and the merged CVEs are
                # carried under it. Entries at two versions only reach here
                # unpackaged: a packaged recipe has a known version, and an
                # entry at any other one was dropped as stale above. Nothing
                # this build ships is described by that version, so the first
                # is as good as the second - first meaning first in sorted
                # filename order, then file order, which makes it stable
                # across runs rather than correct.
                seen_ids = {c.get("id") for c in existing["cves"]}
                added = [c for c in issues if c.get("id") not in seen_ids]
                existing["cves"].extend(added)
                stats.cves += len(added)
                if packaged:
                    stats.packaged_cves += len(added)
                continue

            recipes[name] = {
                "version": version,
                "packaged": packaged,
                "cves": issues,
            }
            stats.cves += len(issues)

            if packaged:
                stats.packaged_recipes += 1
                stats.packaged_cves += len(issues)

    stats.recipes = len(recipes)
    # cvesInRecord "No" means no record matched, not that none exists:
    # cve-check.bbclass skips the products of a CVE it ignored or found
    # already patched, so at AVOCADO_CVE_REPORT_STATUS "Patched" or "Ignored" a
    # recipe can carry issues and still be written with no record on every
    # product. Reporting it as having none while its CVEs sit in "recipes"
    # would put it in two legs of the partition at once, so what the report
    # carries decides.
    return recipes, scanned, scanned - with_record - set(recipes)

def read_optouts(optout_dir):
    """Read the opt-out markers avocado-cve-optout.bbclass writes beside the
    cve-check results.

    Returns (declared, unreadable): a recipe name -> reason map, and the number
    of markers that could not be read. A recipe with no cve-check result and no
    marker was not scanned and nothing says why, which is the case worth
    failing a build over; the reason string is carried so the failure can say
    which mechanism a declared opt-out used.

    Deliberately not part of build_report: the markers explain the report
    rather than belonging to it, and the version 1 envelope is frozen.
    """
    declared = {}
    unreadable = 0

    for path in sorted(glob.glob(os.path.join(optout_dir, "*_optout.json"))):
        try:
            with open(path) as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            unreadable += 1
            continue

        if not isinstance(data, dict):
            unreadable += 1
            continue

        name = data.get("name")
        reason = data.get("reason")
        if not isinstance(name, str) or not name or not isinstance(reason, str):
            unreadable += 1
            continue

        declared[name] = reason

    return declared, unreadable

def read_backports(backports_dir):
    """Read the backport markers avocado-cve-backports.bbclass writes beside
    the cve-check results.

    Returns (backports, unreadable): a recipe name -> set of CVE ids fixed by a
    patch that recipe applies, and the number of markers that would not parse.

    An empty map is not an error, and is what a tree built before the class was
    inherited looks like: every patched issue then reports the "cve-check"
    evidence it would have had anyway. Absence of a marker never means a recipe
    has no backports, only that nothing recorded them - which is why this
    cannot be turned into a coverage check the way read_optouts() is.
    """
    backports = {}
    unreadable = 0

    for path in sorted(glob.glob(os.path.join(backports_dir, "*_backports.json"))):
        try:
            with open(path) as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            unreadable += 1
            continue

        if not isinstance(data, dict):
            unreadable += 1
            continue

        name = data.get("name")
        cves = data.get("cves")
        if (not isinstance(name, str) or not name
                or not isinstance(cves, list)
                or not all(isinstance(c, str) and c for c in cves)):
            unreadable += 1
            continue

        backports[name] = set(cves)

    return backports, unreadable

def packages_digest(packages):
    """Fingerprint of the package set. Consumers re-derive it, so the input
    format is part of the frozen contract.
    """
    digest = hashlib.sha256()
    for name in sorted(packages):
        pkg = packages[name]
        digest.update(
            ("%s\t%s\t%s\n" % (name, pkg["recipe"], pkg["version"])).encode()
        )
    return "sha256:" + digest.hexdigest()

REPORT_VERSION = "1"

def build_report(
    cve_dir,
    pkgdata_dirs,
    machine=None,
    status="Unpatched",
    summary=True,
    manifest_paths=(),
    boot_chain=(),
    backports=None,
    alt_cve_dirs=(),
):
    if status not in CVE_STATUSES:
        raise ValueError(
            "unknown cve-check status %r; expected one of %s"
            % (status, ", ".join(CVE_STATUSES))
        )

    stats = Stats()
    packages, recipe_versions, recipe_version_packages, package_versions = (
        read_pkgdata(pkgdata_dirs, stats)
    )
    recipes, scanned, no_record = read_cve_data(
        cve_dir, recipe_versions, stats, status=status, summary=summary,
        backports=backports, alt_cve_dirs=alt_cve_dirs,
    )

    installed = read_manifests(manifest_paths, stats)
    declared_boot_chain = set(boot_chain)
    recipe_packages = {}
    for name, pkg in packages.items():
        recipe_packages.setdefault(pkg["recipe"], []).append(name)

    # Per-scope totals are deliberately not counters: every entry carries its
    # own, so an aggregate cannot drift from what the entries say.
    for name, entry in recipes.items():
        # Per version: a multi-kernel machine ships one kernel in the rootfs
        # and the other in the feed. The fallback covers a version pkgdata
        # knows no packages under, where both sets are empty anyway.
        by_version = recipe_version_packages.get(name, {})
        for record in [entry] + list(entry.get("alt_versions", ())):
            names = by_version.get(record["version"])
            if names is None and record is entry:
                names = recipe_packages.get(name, ())
            names = names or ()
            # An installed name both versions package belongs to the version
            # the first pkgdata directory - the image's - built. Scored on the
            # bare name, the feed-only kernel reads base-runtime too, which is
            # the one distinction this record exists to make.
            mine = installed.intersection(
                n for n in names
                if record["version"] in package_versions.get(n, ())
            )
            record["scope"] = _scope(name, names, mine, declared_boot_chain)

    # Not a per-scope total but the on-device partition, and keyed on scope
    # rather than pkgdata - the README's "packaged" section has why that is
    # not the same question, and why packaged_* is kept beside it.
    on_device = [e for e in recipes.values() if e["scope"] != "build-only"]
    stats.device_recipes = len(on_device)
    stats.device_cves = sum(len(e["cves"]) for e in on_device)

    # Scope is a field, not a filter, so this denominator does not move: both
    # lists stay derived from pkgdata, and reading a manifest leaves them
    # identical.
    #
    # Both lists are scoped to recipes that shipped a package, so together with
    # the recipes scanned and found in the NVD they partition that set: a
    # consumer can account for every shipped recipe exactly once.
    shipped = {p["recipe"] for p in packages.values()}
    unscanned = sorted(shipped - scanned)
    stats.unscanned_recipes = len(unscanned)
    no_cve_record = sorted(no_record & shipped)
    stats.no_cve_record_recipes = len(no_cve_record)

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
            "device_recipes": stats.device_recipes,
            "device_cves": stats.device_cves,
            "packages": len(packages),
            "cve_files": stats.cve_files,
            "stale_dropped": stats.stale_dropped,
            "unscanned_recipes": stats.unscanned_recipes,
            "no_cve_record_recipes": stats.no_cve_record_recipes,
            "cve_files_unreadable": stats.cve_files_unreadable,
            "pkgdata_unreadable": stats.pkgdata_unreadable,
            "package_collisions": stats.package_collisions,
            "unpatched_cves": stats.unpatched_cves,
            "ignored_cves": stats.ignored_cves,
            "patched_cves": stats.patched_cves,
            "unknown_status_cves": stats.unknown_status_cves,
            "manifests_read": stats.manifests_read,
            "alt_recipes": stats.alt_recipes,
            "alt_cves": stats.alt_cves,
        },
        "recipes": recipes,
        "packages": packages,
        "unscanned_recipes": unscanned,
        "no_cve_record_recipes": no_cve_record,
    }
    if machine:
        report["machine"] = machine

    return report, stats

def status_paths(out_path, statuses):
    """Map each requested status to the file its document is written to.

    The first status keeps out_path. That name is the frozen contract - what
    avocado-cli and Peridio fetch - so asking for a second status adds a
    document beside it rather than renaming the one they read. Every further
    status is suffixed with its own name.

    One document per status rather than one carrying all of them: the envelope
    ENG-2347 froze has a single top-level "status", so this stays an additive
    change to a v1 report instead of a v2. That same field is what says which
    status the unsuffixed document holds.
    """
    stem, ext = os.path.splitext(out_path)
    return {
        s: out_path if i == 0 else "%s-%s%s" % (stem, s.lower(), ext)
        for i, s in enumerate(statuses)
    }

def obsolete_paths(out_path, out_paths):
    """The documents a previous run may have written that this one will not.

    Changing which statuses are asked for changes which suffixed documents
    exist, and nothing prunes DEPLOY_DIR. A
    document left from the other naming reads as a current one: same
    directory, same machine, plausible contents, and only its "generated"
    to give it away. So it is removed rather than left to be found.
    """
    written = set(out_paths.values())
    stem, ext = os.path.splitext(out_path)
    candidates = {out_path} | {
        "%s-%s%s" % (stem, status.lower(), ext) for status in CVE_STATUSES
    }
    return sorted(candidates - written)

def write_report(report, out_path, indent=2):
    """Write one JSON document atomically. indent=None emits it compact."""
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    tmp_path = out_path + ".tmp"
    try:
        with open(tmp_path, "w") as f:
            json.dump(report, f, indent=indent, sort_keys=True)
            f.write("\n")
        os.replace(tmp_path, out_path)
    except BaseException:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

    return out_path

def default_paths(tmpdir, machine=None):
    """Locate both sources under a build's TMPDIR.

    cve-check writes <PN>_cve.json flat into CVE_CHECK_DIR, which upstream
    defaults to ${DEPLOY_DIR}/cve; this layer scopes it per MACHINE, so both
    shapes have to be accepted or the scoped one silently scans nothing. A
    build that redirects DEPLOY_DIR away from ${TMPDIR}/deploy needs
    --cve-dir.
    """
    deploy_cve = os.path.join(tmpdir, "deploy", "cve")
    flat = glob.glob(os.path.join(deploy_cve, "*_cve.json"))
    scoped = sorted(
        d
        for d in glob.glob(os.path.join(deploy_cve, "*"))
        if os.path.isdir(d) and glob.glob(os.path.join(d, "*_cve.json"))
    )
    if machine:
        scoped_for_machine = os.path.join(deploy_cve, machine)
        if scoped_for_machine in scoped or not flat:
            cve_dir = scoped_for_machine
        else:
            cve_dir = deploy_cve
    elif flat and scoped:
        raise ValueError(
            "%s holds both the flat cve-check layout and machine-scoped "
            "subdirectories (%s); pass --machine, or --cve-dir to "
            "read the flat one deliberately"
            % (deploy_cve, ", ".join(os.path.basename(d) for d in scoped))
        )
    elif flat:
        cve_dir = deploy_cve
    else:
        if len(scoped) > 1:
            raise ValueError(
                "%s holds cve-check results for %d machines (%s); pass --machine"
                % (
                    deploy_cve,
                    len(scoped),
                    ", ".join(os.path.basename(d) for d in scoped),
                )
            )
        cve_dir = scoped[0] if scoped else deploy_cve

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
        # any cve-check entry matching the union - so another machine's file
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
    return cve_dir, pkgdata_dirs

def default_manifests(tmpdir, machine=None):
    """Manifests of the images that ship, under a build's TMPDIR.

    Only the two, so a machine's flashing images and the SDK container stay
    out - both would scope base-runtime. The machine suffix is globbed: the
    images carry MACHINE_SHORT_NAME while the directory holding them is
    MACHINE, and only the datastore knows the difference.

    Kept out of default_paths so its return shape stays frozen: an empty result
    is a normal outcome here, not the failure every branch of default_paths
    raises for.
    """
    root = os.path.join(tmpdir, "deploy", "images")
    return sorted(
        path
        for images in glob.glob(os.path.join(root, machine or "*"))
        for image in ("avocado-image-rootfs", "avocado-image-initramfs")
        for path in glob.glob(os.path.join(images, "%s-*.manifest" % image))
    )

def main():
    import argparse
    import sys

    # Spelled out rather than read from __doc__: the module opens with the SPDX
    # comment, and python -OO strips docstrings anyway.
    parser = argparse.ArgumentParser(
        description="Correlate runtime packages with cve-check results"
    )
    parser.add_argument("--tmpdir", help="build TMPDIR, e.g. build/tmp")
    parser.add_argument("--cve-dir", help="override ${DEPLOY_DIR}/cve")
    parser.add_argument(
        "--pkgdata-dir", action="append", default=[], help="override, repeatable"
    )
    parser.add_argument(
        "--machine",
        help="MACHINE recorded in the report, and the ${DEPLOY_DIR}/cve "
        "subdirectory to read when CVE_CHECK_DIR is machine-scoped",
    )
    parser.add_argument(
        "--alt-cve-dir",
        action="append",
        default=[],
        help="a second multiconfig's cve-check results for the same MACHINE, "
        "as avocado-multikernel.bbclass merges them into "
        "${CVE_CHECK_DIR}/<mc>; repeatable. A recipe held here at a second "
        "version becomes an alt_versions record. Not discovered by walking "
        "--cve-dir, which on the unscoped upstream ${DEPLOY_DIR}/cve has one "
        "subdirectory per machine. Pass the matching --pkgdata-dir too, or "
        "every entry is dropped as a stale version",
    )
    parser.add_argument(
        "--status",
        default=list(DEFAULT_STATUSES),
        nargs="+",
        choices=CVE_STATUSES,
        metavar="STATUS",
        help="cve-check status(es) to report on: %s. More than one writes one "
             "document per status, each suffixed onto --output."
             % ", ".join(CVE_STATUSES),
    )
    parser.add_argument(
        "--backports-dir",
        help="directory of <recipe>_backports.json naming the CVEs each "
        "recipe's own patches fix, from avocado-cve-backports.bbclass; "
        "defaults to --cve-dir, which is where the class writes them",
    )
    parser.add_argument(
        "--no-summary", action="store_true", help="drop CVE description text"
    )
    parser.add_argument(
        "--manifest",
        action="append",
        default=[],
        help="image manifest naming the base runtime, repeatable; overrides "
        "the avocado-image-rootfs-*.manifest and avocado-image-initramfs-*"
        ".manifest defaults under ${DEPLOY_DIR}/images/${MACHINE}",
    )
    parser.add_argument(
        "--boot-chain",
        default="",
        help="space-separated recipes that run on the device but are "
        "installed by no package manager, e.g. 'u-boot trusted-firmware-a'",
    )
    parser.add_argument("-o", "--output", required=True)
    args = parser.parse_args()

    cve_dir, pkgdata_dirs = (None, [])
    if args.tmpdir:
        try:
            cve_dir, pkgdata_dirs = default_paths(args.tmpdir, args.machine)
        except ValueError as e:
            parser.error(str(e))
    cve_dir = args.cve_dir or cve_dir
    pkgdata_dirs = args.pkgdata_dir or pkgdata_dirs
    manifests = args.manifest or (
        default_manifests(args.tmpdir, args.machine) if args.tmpdir else []
    )

    if not cve_dir or not pkgdata_dirs:
        parser.error("need --tmpdir, or both --cve-dir and --pkgdata-dir")

    try:
        statuses = parse_statuses(" ".join(args.status))
    except ValueError as e:
        parser.error(str(e))
    out_paths = status_paths(args.output, statuses)

    backports_dir = args.backports_dir or cve_dir
    # Missing globs to nothing, the same as not inheriting the class.
    backports, backports_unreadable = read_backports(backports_dir)

    # Every path removed before any is written: a run that fails partway leaves
    # no stale document from a previous run beside a fresh one, which is the
    # pair a consumer would read as one build. Documents this run will not
    # write go too - see obsolete_paths().
    doomed = list(out_paths.values()) + obsolete_paths(args.output, out_paths)
    pruned = False

    # Over every path, not just the ones written: unlinking a directory raises.
    for path in doomed:
        if os.path.isdir(path):
            parser.error("%s is a directory" % path)

    # One pass per status. pkgdata and the manifests are re-read each time,
    # which is a few seconds against a task whose cost is the world build
    # before it; sharing them would mean threading a prepared state through
    # build_report for no gain a build would notice.
    for status in statuses:
        report, stats = build_report(
            cve_dir,
            pkgdata_dirs,
            machine=args.machine,
            status=status,
            summary=not args.no_summary,
            manifest_paths=manifests,
            boot_chain=args.boot_chain.split(),
            backports=backports,
            alt_cve_dirs=args.alt_cve_dir,
        )

        if not stats.cve_files:
            print(
                "no *_cve.json in %s; nothing was scanned. Was the build run "
                'with INHERIT += "cve-check"? Point --cve-dir at CVE_CHECK_DIR '
                "if it was set to something other than ${DEPLOY_DIR}/cve."
                % cve_dir,
                file=sys.stderr,
            )
            return 1

        # Files found is not files read. A directory of truncated cve-check
        # results passes the check above and produces the same zero-CVE
        # document it exists to prevent, with only a counter line to tell them
        # apart.
        if stats.cve_files_unreadable >= stats.cve_files:
            print(
                "all %d *_cve.json in %s failed to parse; nothing was scanned. "
                "An interrupted build leaves truncated files behind - rerun "
                "the world build, or delete the unreadable ones."
                % (stats.cve_files, cve_dir),
                file=sys.stderr,
            )
            return 1

        if not stats.packages:
            print(
                "no runtime packages found in %s; nothing could be correlated. "
                "pkgdata is written by the packaging tasks, so a cve_check-only "
                "run ('bitbake -c cve_check world') never populates it."
                % ", ".join(pkgdata_dirs),
                file=sys.stderr,
            )
            return 1

        if not pruned:
            # After the checks above, not before: a run that bails on one must
            # not leave the tree emptier than it found it.
            for path in doomed:
                if os.path.exists(path):
                    os.unlink(path)
            pruned = True

        write_report(report, out_paths[status])

        counts = report["counts"]

        print(
            "%s: %d recipes, %d %s CVEs on the device "
            "(%d recipes, %d CVEs scanned; %d, %d packaged; %d packages)"
            % (
                out_paths[status],
                counts["device_recipes"],
                counts["device_cves"],
                status.lower(),
                counts["recipes"],
                counts["cves"],
                counts["packaged_recipes"],
                counts["packaged_cves"],
                counts["packages"],
            ),
            file=sys.stderr,
        )
        # In the loop, unlike the counters below: what a document filtered out
        # is the complement of what it kept, so these three move with status.
        filtered = filtered_counts(counts)
        if filtered:
            print("  filtered out: %s" % filtered, file=sys.stderr)
        # In the loop for the same reason: a recipe whose every record
        # cve-check ignored or found patched carries CVEs in the Patched
        # document and none in the Unpatched one, so which recipes land here
        # moves with the status. read_cve_data() has the reasoning.
        if stats.no_cve_record_recipes:
            print("  no_cve_record_recipes: %d" % stats.no_cve_record_recipes,
                  file=sys.stderr)

    # Once, after the loop: every counter below describes the build rather than
    # the status asked for, so it is identical on every pass and the last one
    # speaks for all of them. Repeating them per status would only double the
    # noise.
    if not stats.manifests_read:
        print(
            "  no image manifest read: every packaged recipe scopes 'feed'. "
            "Pass --manifest, or run after the image tasks have written "
            "${DEPLOY_DIR}/images/%s/*.manifest." % (args.machine or "<machine>"),
            file=sys.stderr,
        )

    for key in (
        "manifests_read",
        "unscanned_recipes",
        "stale_dropped",
        "package_collisions",
        "cve_files_unreadable",
        "pkgdata_unreadable",
    ):
        if stats.get(key):
            print("  %s: %d" % (key, stats[key]), file=sys.stderr)

    if backports_unreadable:
        print(
            "  %d backport marker(s) in %s would not parse; the CVEs they name "
            "report 'cve-check' evidence rather than 'patch-file'"
            % (backports_unreadable, backports_dir),
            file=sys.stderr,
        )

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
