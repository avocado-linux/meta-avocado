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
        "pkgdata_unreadable",
        "package_collisions",
        "stale_dropped",
        "unscanned_recipes",
        "no_cve_record_recipes",
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
# The whole vocabulary cve-check emits: conf/cve-check-map.conf maps every
# CVE_STATUS keyword onto one of these three. Filtering on anything else would
# match no issue at all and produce an empty, CVE-free-looking report.
CVE_STATUSES = ("Unpatched", "Patched", "Ignored")

_FILTERED_COUNTER = {
    "Unpatched": "unpatched_cves",
    "Patched": "patched_cves",
    "Ignored": "ignored_cves",
}

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

def read_cve_data(cve_dir, recipe_versions, stats, status="Unpatched", summary=True):
    fields = (
        CVE_FIELDS
        if summary
        else tuple(f for f in CVE_FIELDS if f not in CVE_SUMMARY_FIELDS)
    )
    recipes = {}
    scanned = set()
    with_record = set()

    paths = sorted(glob.glob(os.path.join(cve_dir, "*_cve.json")))
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

            raw_issues = entry.get("issue", [])
            if not isinstance(raw_issues, list) or not all(
                isinstance(i, dict) for i in raw_issues):
                stats.cve_files_unreadable += 1
                break

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
                # Two entries for one recipe - two files naming it, or two
                # entries in one file. Overwriting would leave the counters
                # holding the replaced entry's CVEs, and a report whose counts
                # exceed what it carries fails its own check as malformed,
                # which no setting overrides. Merge instead, by id: the same
                # CVE reported twice is one CVE.
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
    return recipes, scanned, scanned - with_record

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

def build_report(cve_dir, pkgdata_dirs, machine=None, status="Unpatched", summary=True):
    if status not in CVE_STATUSES:
        raise ValueError(
            "unknown cve-check status %r; expected one of %s"
            % (status, ", ".join(CVE_STATUSES))
        )

    stats = Stats()
    packages, recipe_versions = read_pkgdata(pkgdata_dirs, stats)
    recipes, scanned, no_record = read_cve_data(
        cve_dir, recipe_versions, stats, status=status, summary=summary
    )

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
        },
        "recipes": recipes,
        "packages": packages,
        "unscanned_recipes": unscanned,
        "no_cve_record_recipes": no_cve_record,
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
        "--status",
        default="Unpatched",
        choices=CVE_STATUSES,
        help="cve-check status to report on",
    )
    parser.add_argument(
        "--no-summary", action="store_true", help="drop CVE description text"
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

    if not cve_dir or not pkgdata_dirs:
        parser.error("need --tmpdir, or both --cve-dir and --pkgdata-dir")

    if os.path.isdir(args.output):
        parser.error("--output %s is a directory" % args.output)

    if os.path.exists(args.output):
        os.unlink(args.output)

    report, stats = build_report(
        cve_dir,
        pkgdata_dirs,
        machine=args.machine,
        status=args.status,
        summary=not args.no_summary,
    )

    if not stats.cve_files:
        print(
            "no *_cve.json in %s; nothing was scanned. Was the build run with "
            'INHERIT += "cve-check"? Point --cve-dir at CVE_CHECK_DIR if it was '
            "set to something other than ${DEPLOY_DIR}/cve." % cve_dir,
            file=sys.stderr,
        )
        return 1

    # Files found is not files read. A directory of truncated cve-check results
    # passes the check above and produces the same zero-CVE document it exists
    # to prevent, with only a counter line to tell them apart.
    if stats.cve_files_unreadable >= stats.cve_files:
        print(
            "all %d *_cve.json in %s failed to parse; nothing was scanned. An "
            "interrupted build leaves truncated files behind - rerun the world "
            "build, or delete the unreadable ones." % (stats.cve_files, cve_dir),
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
        "no_cve_record_recipes",
        "stale_dropped",
        "package_collisions",
        "cve_files_unreadable",
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
