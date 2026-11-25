# SPDX-License-Identifier: Apache-2.0

"""The consumer's binding rules for one package of a report, as plain Python.

A report is read by a service that gives every package build a verdict: which
record of its recipe describes it, and what each CVE there means for it. These
are those rules, kept here so the tests can say what a report change does to a
package's verdict rather than only what the JSON looks like. Status "All" only,
which is the only status that service accepts.
"""


def _recipe_record(record, entry, by_version):
    version = entry.get("recipe_version")
    if isinstance(version, str):
        for each in [record] + list(record.get("alt_versions") or []):
            if each.get("version") == version:
                return ("scanned", each["cves"])
        return ("not_checked", "recipe-version-unmatched")
    if by_version:
        return ("not_checked", "recipe-version-unmatched")
    if record.get("alt_versions"):
        return ("not_checked", "recipe-version-unmatched")
    return ("scanned", record["cves"])


def coverage(report, package):
    """("scanned", cves) or ("not_checked", reason) for one package name."""
    entry = report["packages"].get(package)
    if entry is None:
        return ("not_checked", "no-report-entry")
    recipe = entry["recipe"]
    by_version = any(isinstance(p.get("recipe_version"), str)
                     for p in report["packages"].values())
    no_record = report.get("no_cve_record_recipes")
    if recipe in report["unscanned_recipes"]:
        return ("not_checked", "recipe-unscanned")
    if recipe in (no_record or []):
        return ("not_checked", "no-cve-record")
    if isinstance(report["recipes"].get(recipe), dict):
        return _recipe_record(report["recipes"][recipe], entry, by_version)
    if no_record is None:
        return ("not_checked", "coverage-unknown")
    return ("scanned", [])


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


def verdict(report, package):
    """("checked", {cve id: finding}) or ("not_checked", reason)."""
    kind, value = coverage(report, package)
    if kind == "not_checked":
        return kind, value
    return "checked", {c["id"]: finding(c) for c in value if finding(c)}
