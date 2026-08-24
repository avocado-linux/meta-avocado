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
        "unpatched_cves",
        "ignored_cves",
        "patched_cves",
        "unknown_status_cves",
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
    packages = {}
    recipe_versions = {}

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
            recipe_versions.setdefault(recipe, set()).update(
                v for v in (fields.get("PV"), fields.get("PKGV")) if v
            )

            if name in packages:
                if (packages[name]["recipe"] != recipe or
                    packages[name]["version"] != version):
                    stats.package_collisions += 1
                continue

            packages[name] = {
                "recipe": recipe,
                "version": version,
                "origin": origin,
            }

    stats.packages = len(packages)
    return packages, recipe_versions

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

def read_cve_data(manifests, recipe_versions, stats, status="Unpatched", summary=True):
    fields = (
        CVE_FIELDS
        if summary
        else tuple(f for f in CVE_FIELDS if f not in CVE_SUMMARY_FIELDS)
    )
    recipes = {}
    scanned = set()

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

            # An entry exists for every component of the SBOM that was scanned,
            # with an empty "issue" list when nothing matched, so presence is
            # what separates clean from unexamined - including for the entries
            # dropped as stale just below, which were scanned at a version this
            # build does not have. cvesInRecord cannot be used for that here the
            # way it was with cve-check: sbom-cve-check sets it from the
            # exported issue list, so a scanned recipe that came back clean
            # carries "No" too.
            scanned.add(name)

            known = recipe_versions.get(name)
            stripped = _strip_pe(version)
            if not known:
                version = stripped
            elif version not in known:
                if stripped not in known:
                    stats.stale_dropped += 1
                    continue
                version = stripped

            raw_issues = entry.get("issue", [])
            if not isinstance(raw_issues, list) or not all(
                isinstance(i, dict) for i in raw_issues):
                stats.entries_unreadable += 1
                continue

            issues = []
            for issue in raw_issues:
                issue_status = issue.get("status")
                if issue_status == status:
                    issues.append({k: issue[k] for k in fields if k in issue})
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
            if existing is not None:
                # Two entries for one recipe: a directory of manifests, where a
                # per-image export sits beside the world one, or a multilib
                # variant. Merge by CVE id rather than overwrite, or the counts
                # would keep the CVEs the report body just lost.
                seen = {c.get("id") for c in existing["cves"]}
                new = [i for i in issues if i.get("id") not in seen]
                existing["cves"].extend(new)
                stats.cves += len(new)
                if existing["packaged"]:
                    stats.packaged_cves += len(new)
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
    return recipes, scanned

REPORT_VERSION = "1"

def build_report(manifests, pkgdata_dirs, machine=None, status="Unpatched", summary=True):
    if status not in CVE_STATUSES:
        raise ValueError(
            "unknown CVE status %r; expected one of %s"
            % (status, ", ".join(CVE_STATUSES))
        )

    stats = Stats()
    packages, recipe_versions = read_pkgdata(pkgdata_dirs, stats)
    recipes, scanned = read_cve_data(
        manifests, recipe_versions, stats, status=status, summary=summary
    )

    unscanned = sorted({p["recipe"] for p in packages.values()} - scanned)
    stats.unscanned_recipes = len(unscanned)

    digest = hashlib.sha256()
    for name in sorted(packages):
        pkg = packages[name]
        digest.update(
            ("%s\t%s\t%s\n" % (name, pkg["recipe"], pkg["version"])).encode()
        )

    report = {
        "version": REPORT_VERSION,
        "generated": datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "packages_digest": "sha256:" + digest.hexdigest(),
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
            "cve_files_unreadable": stats.cve_files_unreadable,
            "entries_unreadable": stats.entries_unreadable,
            "pkgdata_unreadable": stats.pkgdata_unreadable,
            "package_collisions": stats.package_collisions,
            "unpatched_cves": stats.unpatched_cves,
            "ignored_cves": stats.ignored_cves,
            "patched_cves": stats.patched_cves,
            "unknown_status_cves": stats.unknown_status_cves,
        },
        "recipes": recipes,
        "packages": packages,
        "unscanned_recipes": unscanned,
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
        "--machine",
        help="MACHINE recorded in the report, and the ${DEPLOY_DIR}/images "
        "subdirectory the manifest is read from",
    )
    parser.add_argument(
        "--status",
        default="Unpatched",
        choices=CVE_STATUSES,
        help="CVE status to report on",
    )
    parser.add_argument(
        "--no-summary", action="store_true", help="drop CVE description text"
    )
    parser.add_argument("-o", "--output", required=True)
    args = parser.parse_args()

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

    write_report(report, args.output)

    counts = report["counts"]

    print(
        "%s: %d packages, %d recipes, %d %s CVEs (%d recipes, %d CVEs packaged)"
        % (
            args.output,
            counts["packages"],
            counts["recipes"],
            counts["cves"],
            args.status.lower(),
            counts["packaged_recipes"],
            counts["packaged_cves"],
        ),
        file=sys.stderr,
    )
    for key in (
        "unscanned_recipes",
        "stale_dropped",
        "package_collisions",
        "cve_files_unreadable",
        "entries_unreadable",
        "pkgdata_unreadable",
        "unpatched_cves",
        "ignored_cves",
        "patched_cves",
        "unknown_status_cves",
    ):
        if stats.get(key):
            print("  %s: %d" % (key, stats[key]), file=sys.stderr)

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
