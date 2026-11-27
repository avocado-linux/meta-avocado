#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""The compiled-source filter's not-applicable-config stands only for recipes
whose build lists the sources it compiled.

sbom-cve-check reads a build's source files as the recipe's compiled sources.
A recipe built without SPDX_INCLUDE_COMPILED_SOURCES lists only the files it
fetched, so a CVE in a source file reads as not compiled. The report lists
such a CVE as Unpatched instead, at build time and on a rebuild from a
previous report.

  cd meta-avocado-sbom/tests && PYTHONPATH=../lib python3 -m unittest discover -p 'test_*.py'
"""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

from avocado_sbom import report  # noqa: E402

FILTERED = {"detail": report.COMPILED_SOURCE_DETAIL,
            "description": report.COMPILED_SOURCE_DESCRIPTION}


def issue(cve, status, **extra):
    item = {"id": cve, "status": status, "summary": "s " + cve, "scorev3": "5.9",
            "link": "l " + cve}
    item.update(extra)
    return item


def entry(name, version, product, *issues):
    return {"name": name, "version": version, "issue": list(issues),
            "products": [{"product": product, "cvesInRecord": "Yes"}]}


# libpam: the scanner dropped a CVE in a file the build never fetched by name;
# a recipe's own CVE_STATUS with the same detail; and an ordinary Unpatched.
LIBPAM = entry(
    "libpam", "1.7.2", "linux-pam",
    issue("CVE-2026-54411", "Ignored", **FILTERED),
    issue("CVE-2026-0002", "Ignored", detail="not-applicable-config",
          description="vulnerable_code_not_present: pam_userdb is disabled"),
    issue("CVE-2026-0003", "Unpatched", detail="version-in-range"))
KERNEL = entry(
    "linux-raspberrypi", "6.12.47+git", "linux_kernel",
    issue("CVE-2026-1001", "Ignored", **FILTERED),
    issue("CVE-2026-1002", "Unpatched", detail="version-in-range"))


class Build:
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="report-compiled-")
        self.addCleanup(shutil.rmtree, self.root)
        self.pkgdata = os.path.join(self.root, "pkgdata", "raspberrypi5")
        os.makedirs(os.path.join(self.pkgdata, "runtime-reverse"))
        for name, pn, pv in (("libpam", "libpam", "1.7.2"),
                             ("kernel-image", "linux-raspberrypi", "6.12.47+git")):
            with open(os.path.join(self.pkgdata, "runtime-reverse", name), "w") as f:
                f.write("PN: %s\nPV: %s\nPKGV: %s\nPKGR: r0\n" % (pn, pv, pv))
        self.manifest = os.path.join(self.root, "scan" + report.MANIFEST_SUFFIX)
        with open(self.manifest, "w") as f:
            json.dump({"version": "1", "package": [LIBPAM, KERNEL]}, f)

    def build(self, compiled_sources=None, status=report.STATUS_ALL, summary=True):
        doc, _stats = report.build_report(
            [self.manifest], [self.pkgdata], machine="raspberrypi5", status=status,
            summary=summary, compiled_sources=compiled_sources)
        return doc

    @staticmethod
    def cves(doc, build):
        return {c["id"]: c for c in doc["builds"].get(build, {}).get("cves", [])}

    @staticmethod
    def flags(doc):
        return {b: v["compiled_sources"] for b, v in doc["builds"].items()
                if "compiled_sources" in v}


class BuildReportTest(Build, unittest.TestCase):
    def test_a_recipe_without_the_setting_gets_unpatched(self):
        doc = self.build(compiled_sources={"linux-raspberrypi"})
        cve = self.cves(doc, "libpam")["CVE-2026-54411"]
        self.assertEqual(cve["status"], "Unpatched")
        self.assertNotIn("detail", cve)
        self.assertNotIn("description", cve)
        self.assertEqual(cve["scanner"], dict(status="Ignored", **FILTERED))
        self.assertEqual(cve["summary"], "s CVE-2026-54411")

    def test_a_recipe_with_the_setting_keeps_the_filter(self):
        doc = self.build(compiled_sources={"linux-raspberrypi"})
        cve = self.cves(doc, "linux-raspberrypi")["CVE-2026-1001"]
        self.assertEqual(cve, dict(issue("CVE-2026-1001", "Ignored", **FILTERED)))

    def test_a_non_kernel_recipe_with_the_setting_keeps_it_too(self):
        doc = self.build(compiled_sources={"linux-raspberrypi", "libpam"})
        self.assertEqual(self.cves(doc, "libpam")["CVE-2026-54411"]["status"], "Ignored")
        self.assertEqual(doc["counts"]["unverified_compiled_source_cves"], 0)

    def test_a_kernel_without_the_setting_gets_unpatched(self):
        doc = self.build(compiled_sources=set())
        self.assertEqual(self.cves(doc, "linux-raspberrypi")["CVE-2026-1001"]["status"],
                         "Unpatched")

    def test_a_recipes_own_cve_status_stays_ignored(self):
        doc = self.build(compiled_sources=set())
        cve = self.cves(doc, "libpam")["CVE-2026-0002"]
        self.assertEqual((cve["status"], cve["detail"]), ("Ignored", "not-applicable-config"))
        self.assertNotIn("scanner", cve)

    def test_only_an_ignored_result_is_turned(self):
        with open(self.manifest, "w") as f:
            json.dump({"version": "1", "package": [entry(
                "libpam", "1.7.2", "linux-pam",
                issue("CVE-2026-0004", "Patched", **FILTERED))]}, f)
        doc = self.build(compiled_sources=set())
        cve = self.cves(doc, "libpam")["CVE-2026-0004"]
        self.assertEqual((cve["status"], cve["detail"]), ("Patched", "not-applicable-config"))

    def test_a_direct_result_wins_over_a_turned_one_in_either_order(self):
        direct = entry("libpam", "1.7.2", "linux-pam",
                       issue("CVE-2026-54411", "Unpatched", detail="version-in-range"))
        for order in ([LIBPAM, direct], [direct, LIBPAM]):
            for i, e in enumerate(order):
                with open(os.path.join(self.root, "m%d%s" % (i, report.MANIFEST_SUFFIX)), "w") as f:
                    json.dump({"version": "1", "package": [e]}, f)
            for status in (report.STATUS_ALL, "Unpatched"):
                doc, _stats = report.build_report(
                    [os.path.join(self.root, "m%d%s" % (i, report.MANIFEST_SUFFIX))
                     for i in range(2)],
                    [self.pkgdata], status=status, compiled_sources=set())
                cve = self.cves(doc, "libpam")["CVE-2026-54411"]
                self.assertEqual(cve["detail"], "version-in-range", (order[0]["issue"], status))
                self.assertNotIn("scanner", cve)
                self.assertEqual(doc["counts"]["unverified_compiled_source_cves"], 0)

    def test_a_turned_result_stands_against_another_status(self):
        other = entry("libpam", "1.7.2", "linux-pam",
                      issue("CVE-2026-54411", "Patched", detail="version-not-in-range"))
        for i, e in enumerate([LIBPAM, other]):
            with open(os.path.join(self.root, "m%d%s" % (i, report.MANIFEST_SUFFIX)), "w") as f:
                json.dump({"version": "1", "package": [e]}, f)
        doc, _stats = report.build_report(
            [os.path.join(self.root, "m%d%s" % (i, report.MANIFEST_SUFFIX)) for i in range(2)],
            [self.pkgdata], status=report.STATUS_ALL, compiled_sources=set())
        cve = self.cves(doc, "libpam")["CVE-2026-54411"]
        self.assertEqual(cve["status"], "Unpatched")
        self.assertNotIn("detail", cve)
        self.assertIn("scanner", cve)

    def test_listed_at_status_unpatched_and_not_at_ignored(self):
        doc = self.build(compiled_sources=set(), status="Unpatched")
        self.assertIn("CVE-2026-54411", self.cves(doc, "libpam"))
        self.assertNotIn("status", self.cves(doc, "libpam")["CVE-2026-54411"])
        doc = self.build(compiled_sources=set(), status="Ignored")
        self.assertNotIn("CVE-2026-54411", self.cves(doc, "libpam"))
        self.assertIn("CVE-2026-0002", self.cves(doc, "libpam"))

    def test_counts(self):
        doc = self.build(compiled_sources={"linux-raspberrypi"})
        counts = doc["counts"]
        self.assertEqual(counts["unverified_compiled_source_cves"], 1)
        self.assertEqual((counts["unpatched_cves"], counts["ignored_cves"]), (3, 2))
        doc = self.build(compiled_sources=set())
        self.assertEqual(doc["counts"]["unverified_compiled_source_cves"], 2)

    def test_without_summary_the_scanner_field_stays(self):
        doc = self.build(compiled_sources=set(), summary=False)
        cve = self.cves(doc, "libpam")["CVE-2026-54411"]
        self.assertEqual(cve["scanner"], dict(status="Ignored", **FILTERED))
        self.assertNotIn("summary", cve)

    def test_the_report_carries_a_flag_on_every_build(self):
        doc = self.build(compiled_sources=["linux-raspberrypi"])
        self.assertEqual(self.flags(doc), {"libpam": False, "linux-raspberrypi": True})

    def test_a_function_is_asked_for_every_build_in_package_data(self):
        asked = []

        def opted_in(mc, recipe):
            asked.append((mc, recipe))
            return recipe.startswith("linux-")
        doc = self.build(compiled_sources=opted_in)
        self.assertEqual(sorted(asked), [("", "libpam"), ("", "linux-raspberrypi")])
        self.assertEqual(self.flags(doc), {"libpam": False, "linux-raspberrypi": True})
        self.assertEqual(self.cves(doc, "libpam")["CVE-2026-54411"]["status"], "Unpatched")

    def test_unknown_trusts_kernels_only_and_writes_no_flag(self):
        doc = self.build(compiled_sources=None)
        self.assertEqual(self.flags(doc), {})
        self.assertEqual(self.cves(doc, "linux-raspberrypi")["CVE-2026-1001"]["status"],
                         "Ignored")
        self.assertEqual(self.cves(doc, "libpam")["CVE-2026-54411"]["status"], "Unpatched")


class TrustTest(unittest.TestCase):
    def test_the_flag_decides_when_known(self):
        self.assertTrue(report.trusts_compiled_sources("busybox", set(), {"busybox"}.__contains__))
        self.assertFalse(report.trusts_compiled_sources(
            "linux-yocto-rt", {"linux_kernel"}, {"linux-yocto"}.__contains__))

    def test_unknown_trusts_the_kernel_product(self):
        self.assertTrue(report.trusts_compiled_sources("linux-x", {"linux_kernel"}, None))
        self.assertFalse(report.trusts_compiled_sources("libpam", {"linux-pam"}, None))
        self.assertFalse(report.trusts_compiled_sources("libpam", set(), None))


    def test_a_malformed_product_neither_aborts_nor_establishes_trust(self):
        entry = {"products": [{"product": []}, {"product": {"x": 1}}, "linux_kernel",
                              {"product": "linux_kernel"}, {}]}
        self.assertEqual(report._entry_products(entry), {"linux_kernel"})
        self.assertEqual(report._entry_products({"products": [{"product": None}]}), set())


class FromAnchorTest(Build, unittest.TestCase):
    def rebuild(self, anchor):
        doc, _stats = report.build_report_from_anchor([self.manifest], anchor)
        return doc

    def same(self, a, b):
        a, b = dict(a), dict(b)
        a["generated"] = b["generated"] = "x"
        self.assertEqual(a, b)

    def test_a_rescan_applies_the_carried_flags(self):
        built = self.build(compiled_sources={"linux-raspberrypi", "libpam"})
        rebuilt = self.rebuild(built)
        self.same(rebuilt, built)
        self.assertEqual(self.cves(rebuilt, "libpam")["CVE-2026-54411"]["status"], "Ignored")

    def test_a_rescan_of_no_flag_set_trusts_nothing(self):
        built = self.build(compiled_sources=set())
        self.assertEqual(self.flags(built), {"libpam": False, "linux-raspberrypi": False})
        rebuilt = self.rebuild(built)
        self.same(rebuilt, built)
        self.assertEqual(self.cves(rebuilt, "linux-raspberrypi")["CVE-2026-1001"]["status"],
                         "Unpatched")

    def test_a_report_without_the_flags_trusts_kernels_only(self):
        built = self.build(compiled_sources={"linux-raspberrypi", "libpam"})
        for build in built["builds"].values():
            del build["compiled_sources"]
        rebuilt = self.rebuild(built)
        self.assertEqual(self.flags(rebuilt), {})
        self.assertEqual(self.cves(rebuilt, "libpam")["CVE-2026-54411"]["status"], "Unpatched")
        self.assertEqual(self.cves(rebuilt, "linux-raspberrypi")["CVE-2026-1001"]["status"],
                         "Ignored")
        self.same(rebuilt, self.build(compiled_sources=None))

    def test_a_malformed_flag_is_refused(self):
        built = self.build(compiled_sources={"linux-raspberrypi"})
        for bad in ("yes", 1, None, []):
            built["builds"]["libpam"]["compiled_sources"] = bad
            with self.assertRaises(ValueError) as cm:
                self.rebuild(built)
            self.assertIn("builds['libpam'] is malformed", str(cm.exception))


class CliTest(Build, unittest.TestCase):
    def run_main(self, *argv):
        err = io.StringIO()
        with mock.patch.object(sys, "argv", ["report.py"] + list(argv)), \
                contextlib.redirect_stderr(err):
            try:
                code = report.main()
            except SystemExit as e:
                code = e.code
        return code, err.getvalue()

    def test_the_option_names_the_recipes(self):
        out = os.path.join(self.root, "out.json")
        code, _err = self.run_main(
            "--manifest", self.manifest, "--pkgdata-dir", self.pkgdata, "--status", "All",
            "--compiled-source-recipe", "linux-raspberrypi", "-o", out)
        self.assertEqual(code, 0)
        with open(out) as f:
            doc = json.load(f)
        self.assertEqual(self.flags(doc), {"libpam": False, "linux-raspberrypi": True})
        self.assertEqual(self.cves(doc, "libpam")["CVE-2026-54411"]["status"], "Unpatched")

    def test_without_the_option_no_flag(self):
        out = os.path.join(self.root, "out.json")
        code, _err = self.run_main(
            "--manifest", self.manifest, "--pkgdata-dir", self.pkgdata, "--status", "All",
            "-o", out)
        self.assertEqual(code, 0)
        with open(out) as f:
            self.assertEqual(self.flags(json.load(f)), {})

    def test_the_option_conflicts_with_a_previous_report(self):
        code, err = self.run_main(
            "--manifest", self.manifest, "--from-report", self.manifest,
            "--compiled-source-recipe", "libpam", "-o", os.path.join(self.root, "o.json"))
        self.assertEqual(code, 2)
        self.assertIn("--compiled-source-recipe", err)


RECIPE = os.path.join(HERE, "..", "recipes-avocado", "avocado-cve-report",
                      "avocado-cve-report.bb")


class D:
    """The datastore slice do_cve_report reads; NAME:pn-<recipe> values are
    stored under that name, as local.conf's are."""

    def __init__(self, values):
        self.values = values

    def getVar(self, name, expand=True):
        return self.values.get(name)


class Fatal(Exception):
    pass


class RecipeHarness(Build):
    """Runs do_cve_report, with the recipe's avocado_cve_* helpers, against a
    datastore slice."""

    def run_task(self, values):
        import re
        import textwrap
        import types
        with open(RECIPE) as f:
            text = f.read()
        body = re.search(r"^python do_cve_report\(\) \{\n(.*?)^\}\n", text, re.M | re.S)
        helpers = re.findall(r"^(def avocado_cve_\w+\(.*?)(?=^\S)", text, re.M | re.S)

        def fatal(msg):
            raise Fatal(msg)
        bb = types.SimpleNamespace(
            fatal=fatal, plain=lambda *a: None, note=lambda *a: None, warn=lambda *a: None,
            utils=types.SimpleNamespace(
                remove=lambda p: os.path.exists(p) and os.remove(p),
                to_boolean=lambda s, default: default if not s else s in ("1", "yes", "true")))
        out = os.path.join(self.root, "report.json")
        settings = dict(AVOCADO_CVE_REPORT_FILE=out, AVOCADO_CVE_MANIFEST=self.manifest,
                        PKGDATA_DIR=self.pkgdata, MACHINE="avocado-raspberrypi5",
                        AVOCADO_CVE_REPORT_STATUS="All", AVOCADO_CVE_SCOPE="image")
        settings.update(values)
        d = D(settings)
        ns = {"bb": bb, "os": os, "d": d}
        for helper in helpers:
            exec(helper, ns)
        exec("def task(d):\n" + textwrap.indent(textwrap.dedent(body.group(1)), "    "), ns)
        ns["task"](d)
        with open(out) as f:
            return json.load(f)

    def feed(self, record, alt_packages=(), merged=()):
        """Feed scope, with an alternate multiconfig building the 6.6 kernel
        and the coverage record do_feed_sbom wrote; record None writes none.
        alt_packages are more (name, recipe, version) in its pkgdata, merged
        the paths its merge published."""
        top = os.path.join(self.root, "top")
        alt = os.path.join(top, "tmp-rpi-6_6", "pkgdata", "raspberrypi5", "runtime-reverse")
        os.makedirs(alt)
        for name, pn, pv in (("kernel-image", "linux-raspberrypi", "6.6.78+git"),) + tuple(
                alt_packages):
            with open(os.path.join(alt, name), "w") as f:
                f.write("PN: %s\nPV: %s\nPKGV: %s\nPKGR: r0\n" % (pn, pv, pv))
        deploy = os.path.join(self.root, "deploy")
        os.makedirs(os.path.join(deploy, "avocado-multikernel"), exist_ok=True)
        with open(os.path.join(deploy, "avocado-multikernel", "rpi-6_6-rpms.txt"), "w") as f:
            f.writelines(path + "\n" for path in merged)
        coverage = os.path.join(self.root, "feed.coverage.json")
        if record is not None:
            with open(coverage, "w") as f:
                json.dump(record, f)
        return self.run_task({
            "AVOCADO_CVE_SCOPE": "feed", "TOPDIR": top, "TMPDIR": self.root,
            "DEPLOY_DIR": deploy, "DEPLOY_DIR_RPM": os.path.join(deploy, "rpm"),
            "AVOCADO_MULTIKERNEL_MC_RECIPES": "rpi-6_6:linux-raspberrypi",
            "AVOCADO_FEED_COVERAGE_FILE": coverage})


class RecipeTest(RecipeHarness, unittest.TestCase):
    """do_cve_report hands the per-recipe setting, and at feed scope the
    builds the feed document left out, to the report."""

    def test_the_pn_setting_decides(self):
        doc = self.run_task({"SPDX_INCLUDE_COMPILED_SOURCES:pn-linux-raspberrypi": "1"})
        self.assertEqual(self.flags(doc), {"libpam": False, "linux-raspberrypi": True})
        self.assertEqual(self.cves(doc, "libpam")["CVE-2026-54411"]["status"], "Unpatched")
        self.assertEqual(self.cves(doc, "linux-raspberrypi")["CVE-2026-1001"]["status"],
                         "Ignored")

    def test_at_feed_scope_the_coverage_record_names_the_builds_left_out(self):
        reason = "VEX overlap: linux_kernel 6.6.78+git is also x, with other statements on y"
        doc = self.feed({"alt_not_covered": [
            {"mc": "rpi-6_6", "recipe": "linux-raspberrypi", "reason": reason},
            {"mc": "", "recipe": "broken", "reason": "malformed entry"}]})
        alt = doc["builds"]["rpi-6_6:linux-raspberrypi"]
        self.assertEqual((alt["coverage"], alt["not_covered"]), ("unscanned", reason))
        self.assertEqual(doc["packages"]["kernel-image"], [
            {"version": "6.12.47+git-r0", "build": "linux-raspberrypi"},
            {"version": "6.6.78+git-r0", "build": "rpi-6_6:linux-raspberrypi"}])
        self.assertEqual(doc["counts"]["not_covered_builds"], 1)

    def test_at_feed_scope_a_missing_coverage_record_fails(self):
        for record in (None, {"alt_included": []}):
            with self.subTest(record=record):
                with self.assertRaises(Fatal) as ctx:
                    self.feed(record)
                self.assertIn("coverage record", str(ctx.exception))
                self.assertFalse(os.path.exists(os.path.join(self.root, "report.json")))
                shutil.rmtree(os.path.join(self.root, "top"))

    def test_nothing_set_trusts_nothing(self):
        doc = self.run_task({})
        self.assertEqual(self.flags(doc), {"libpam": False, "linux-raspberrypi": False})
        self.assertEqual(self.cves(doc, "linux-raspberrypi")["CVE-2026-1001"]["status"],
                         "Unpatched")


if __name__ == "__main__":
    unittest.main()
