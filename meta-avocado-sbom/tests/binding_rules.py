# SPDX-License-Identifier: Apache-2.0

"""The consumer's rules for a version 2 report and its RPM manifest, as plain
Python.

A report is read by a service that gives every RPM a verdict: which package
build it is, which build that is, and what each CVE of that build's record
means for it. These are those rules, kept here so the tests can say what a
report change does to an RPM's verdict rather than only what the JSON looks
like. Status "All" only, which is the only status that service accepts.
"""


class Rejected(ValueError):
    """The service refuses the whole upload."""


def normalize(version):
    if ":" in version and version.split(":", 1)[0].isdigit():
        version = version.split(":", 1)[1]
    return version.replace("+", "-")


def validate(report, manifest):
    """Raise Rejected as the service does on intake."""
    if report.get("version") != "2":
        raise Rejected("report.version %s is not supported" % report.get("version"))
    builds = report.get("builds")
    if not isinstance(builds, dict):
        raise Rejected("builds is not a map")
    for bid, build in builds.items():
        if not isinstance(build.get("recipe"), str) or build.get("coverage") not in (
                "scanned", "no-cve-record", "unscanned"):
            raise Rejected("builds.%s is malformed" % bid)
    for name, entries in report["packages"].items():
        if not isinstance(entries, list) or not entries:
            raise Rejected("packages.%s is not a non-empty list" % name)
        seen = set()
        for entry in entries:
            if entry.get("build") not in builds:
                raise Rejected("packages.%s names unknown build %s" % (name, entry.get("build")))
            key = normalize(entry["version"])
            if key in seen:
                raise Rejected("packages.%s lists %s twice" % (name, key))
            seen.add(key)
    for rpm in manifest["packages"]:
        if package_build(report, rpm) is None:
            raise Rejected("rpm_manifest: %s %s-%s is not in the report's packages"
                           % (rpm["name"], rpm["version"], rpm["release"]))


def package_build(report, rpm):
    """The package build an RPM joins: same name, same normalized
    version-release. None when there is none."""
    want = normalize("%s-%s" % (rpm["version"], rpm["release"]))
    for entry in report["packages"].get(rpm["name"], ()):
        if normalize(entry["version"]) == want:
            return entry
    return None


def build_coverage(report, bid):
    """("scanned", cves) or ("not_checked", reason) for one build."""
    build = report["builds"][bid]
    if build["coverage"] == "scanned":
        return ("scanned", build["cves"])
    if build["coverage"] == "no-cve-record":
        return ("not_checked", "no-cve-record")
    if "not_covered" in build:
        return ("not_checked", "build-not-covered")
    return ("not_checked", "build-unscanned")


def _detail(cve):
    if isinstance(cve.get("detail"), str):
        return cve["detail"]
    if cve.get("status") == "Unpatched":
        return "unpatched"
    if cve.get("status") == "Patched" and cve.get("evidence") == "patch-file":
        return "fix-file-included"
    if cve.get("status") == "Patched" and cve.get("evidence") == "cve-check":
        return "version-not-in-range"
    return None


def finding(cve):
    """"affected", "unassessed", "patched" or None (not listed) for one CVE."""
    detail = _detail(cve)
    if detail is None:
        # The consumer rejects the whole report over one such row.
        raise ValueError("%s has no readable detail" % cve.get("id"))
    reason = detail.split(":", 1)[0].strip()
    status = cve["status"]
    if status == "Unpatched":
        return "affected" if reason in ("version-in-range", "unpatched") else "unassessed"
    if status == "Patched":
        return "patched"
    if status == "Ignored" and reason == "upstream-wontfix":
        return "affected"
    return None


def build_verdict(report, bid):
    """("checked", {cve id: finding}) or ("not_checked", reason) for one build."""
    kind, value = build_coverage(report, bid)
    if kind == "not_checked":
        return kind, value
    return "checked", {c["id"]: finding(c) for c in value if finding(c)}


def rpm_verdicts(report, manifest):
    """{(name, version, release, arch): verdict} for each RPM of a manifest,
    after validate: each RPM joins its package build, then that build's
    record. Two RPMs that join one package build (their arch differs) are
    ambiguous."""
    validate(report, manifest)
    joins = [(rpm, package_build(report, rpm)) for rpm in manifest["packages"]]
    count = {}
    for _rpm, entry in joins:
        count[id(entry)] = count.get(id(entry), 0) + 1
    result = {}
    for rpm, entry in joins:
        key = (rpm["name"], rpm["version"], rpm["release"], rpm["arch"])
        result[key] = (("not_checked", "ambiguous-version") if count[id(entry)] > 1
                       else build_verdict(report, entry["build"]))
    return result


def package_verdict(report, name, version):
    """The verdict of the package build of name at version (PKGV-PKGR)."""
    for entry in report["packages"][name]:
        if normalize(entry["version"]) == normalize(version):
            return build_verdict(report, entry["build"])
    raise KeyError((name, version))
