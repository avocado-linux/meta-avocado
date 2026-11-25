# SPDX-License-Identifier: Apache-2.0
"""avocado-spdx-vex-notes.bbclass: CVE_STATUS detail in the VEX status notes.

The class wraps what scarthgap's oe.spdx30_tasks.create_spdx calls, so the
tests drive it the way create_spdx does: _get_cves_info through the module
global, new_cve_vuln, the alias, then one new_vex_* per CVE and package with
the CVE's link id. The notes must be what OE-core writes from wrynose on:
the detail on Ignored, "detail: description" on Patched and Unpatched.

RealLibTests run the same against scarthgap OE-core's own oe.sbom30 and
oe.spdx30 when OE_CORE_LIB names that tree's meta/lib.

Run with:
    python3 -m unittest discover -s meta-avocado/tests
"""

import importlib.util
import os
import re
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLASS = ROOT / "meta-avocado" / "classes" / "avocado-spdx-vex-notes.bbclass"
FEATURE = ROOT / "kas" / "feature"

STATUSES = [
    ("CVE-2013-4235", "Ignored", "upstream-wontfix", "shadow never fixed it"),
    ("CVE-2020-1000", "Ignored", "not-applicable-config", ""),
    ("CVE-2024-2961", "Patched", "cpe-stable-backport", "Fixed in 2.39.1"),
    ("CVE-2021-42380", "Patched", "backported-patch", None),
    ("CVE-2025-0001", "Unpatched", "unpatched", "no fix yet"),
]
EXPECTED = {
    "CVE-2013-4235": "upstream-wontfix",
    "CVE-2020-1000": "not-applicable-config",
    "CVE-2024-2961": "cpe-stable-backport: Fixed in 2.39.1",
    "CVE-2021-42380": "backported-patch",
    "CVE-2025-0001": "unpatched: no fix yet",
}


def install_function():
    m = re.search(r"^def avocado_spdx_vex_notes_install\(\):\n(.*?)(?=^\S)",
                  CLASS.read_text() + "\n#", re.M | re.S)
    assert m, "avocado_spdx_vex_notes_install is gone from the class"
    ns = {}
    exec("def avocado_spdx_vex_notes_install():\n" + m.group(1), ns)
    return ns["avocado_spdx_vex_notes_install"]


def create_spdx_vex(oe, d, build_objset, pkg_objsets):
    """scarthgap create_spdx's two CVE loops, call for call."""
    cve_by_status = {}
    for cve_id, mapping, detail, description in oe.spdx30_tasks._get_cves_info(d):
        spdx_cve = build_objset.new_cve_vuln(cve_id)
        build_objset.set_element_alias(spdx_cve)
        cve_by_status.setdefault(mapping, {})[cve_id] = (spdx_cve, detail, description)

    notes = {}
    for pkg_objset, spdx_package in pkg_objsets:
        for status, cves in cve_by_status.items():
            for cve, (spdx_cve, detail, description) in cves.items():
                spdx_cve_id = oe.sbom30.get_element_link_id(spdx_cve)
                if status == "Patched":
                    rels = pkg_objset.new_vex_patched_relationship([spdx_cve_id], [spdx_package])
                elif status == "Unpatched":
                    rels = pkg_objset.new_vex_unpatched_relationship([spdx_cve_id], [spdx_package])
                else:
                    rels = pkg_objset.new_vex_ignored_relationship(
                        [spdx_cve_id], [spdx_package], impact_statement=description)
                for r in rels:
                    notes.setdefault(cve, set()).add(getattr(r, "security_statusNotes", None))
    return notes


class FakeOe:
    """The slice of oe.sbom30 and oe.spdx30_tasks the class touches."""

    def __init__(self):
        class Vuln:
            def __init__(self, cve):
                self._id = "http://spdx.org/spdxdocs/x/vulnerability/" + cve
                self.alias = None

        class Rel:
            pass

        class ObjectSet:
            def new_cve_vuln(self, cve):
                return Vuln(cve)

            def set_element_alias(self, e):
                e.alias = "http://spdxdocs.org/openembedded-alias/by-doc-hash/x/" + e._id.rsplit("/", 1)[1]

            def new_vex_patched_relationship(self, from_, to):
                return [Rel()]

            def new_vex_unpatched_relationship(self, from_, to):
                return [Rel()]

            def new_vex_ignored_relationship(self, from_, to, *, impact_statement):
                r = Rel()
                r.security_impactStatement = impact_statement
                return [r]

        def get_element_link_id(e):
            return e.alias or e._id

        def _get_cves_info(d):
            for cve, mapping, detail, description in STATUSES:
                yield cve, mapping, detail, description

        self.ObjectSet = ObjectSet
        self.sbom30 = types.SimpleNamespace(ObjectSet=ObjectSet, get_element_link_id=get_element_link_id)
        self.spdx30_tasks = types.SimpleNamespace(_get_cves_info=_get_cves_info)
        self.package = types.ModuleType("oe")
        self.package.sbom30 = self.sbom30
        self.package.spdx30_tasks = self.spdx30_tasks


class Modules:
    """Put an oe package in sys.modules for the duration of a test."""

    def __init__(self, test, modules):
        saved = {k: sys.modules.get(k) for k in modules}
        sys.modules.update(modules)

        def restore():
            for k, v in saved.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v
        test.addCleanup(restore)


class FakeTests(unittest.TestCase):
    def setUp(self):
        self.oe = FakeOe()
        Modules(self, {"oe": self.oe.package, "oe.sbom30": self.oe.sbom30,
                       "oe.spdx30_tasks": self.oe.spdx30_tasks})

    def run_vex(self, packages=2):
        objset = self.oe.ObjectSet()
        pkgs = [(self.oe.ObjectSet(), "pkg%d" % i) for i in range(packages)]
        return create_spdx_vex(self.oe.package, None, objset, pkgs)

    def test_without_the_class_there_are_no_notes(self):
        self.assertEqual({c: n for c, n in self.run_vex().items()},
                         {c: {None} for c in EXPECTED})

    def test_notes_match_upstream_on_every_package(self):
        install_function()()
        self.assertEqual(self.run_vex(packages=3), {c: {n} for c, n in EXPECTED.items()})

    def test_installing_twice_wraps_once(self):
        install = install_function()
        install()
        patched = self.oe.ObjectSet.new_vex_patched_relationship
        install()
        self.assertIs(self.oe.ObjectSet.new_vex_patched_relationship, patched)

    def test_the_ignored_statement_keeps_its_impact_statement(self):
        install_function()()
        objset = self.oe.ObjectSet()
        v = objset.new_cve_vuln("CVE-2013-4235")
        objset.set_element_alias(v)
        list(self.oe.spdx30_tasks._get_cves_info(None))
        r, = objset.new_vex_ignored_relationship(
            [self.oe.sbom30.get_element_link_id(v)], ["pkg"], impact_statement="why")
        self.assertEqual((r.security_impactStatement, r.security_statusNotes),
                         ("why", "upstream-wontfix"))

    def test_a_cve_with_no_status_gets_no_notes(self):
        install_function()()
        objset = self.oe.ObjectSet()
        v = objset.new_cve_vuln("CVE-1999-0001")
        objset.set_element_alias(v)
        r, = objset.new_vex_patched_relationship([self.oe.sbom30.get_element_link_id(v)], ["pkg"])
        self.assertFalse(hasattr(r, "security_statusNotes"))


@unittest.skipUnless(os.environ.get("OE_CORE_LIB"),
                     "set OE_CORE_LIB to scarthgap OE-core's meta/lib to run against it")
class RealLibTests(unittest.TestCase):
    def setUp(self):
        lib = Path(os.environ["OE_CORE_LIB"])
        bb = types.ModuleType("bb")
        bb.warn = bb.note = bb.debug = lambda *a, **k: None
        bb.fatal = lambda msg: (_ for _ in ()).throw(RuntimeError(msg))
        oe = types.ModuleType("oe")
        oe.__path__ = []
        packagedata = types.ModuleType("oe.packagedata")
        oe.packagedata = packagedata
        Modules(self, {"bb": bb, "oe": oe, "oe.packagedata": packagedata})
        for name in ("spdx30", "spdx_common", "sbom30"):
            spec = importlib.util.spec_from_file_location("oe." + name, lib / "oe" / (name + ".py"))
            mod = importlib.util.module_from_spec(spec)
            Modules(self, {"oe." + name: mod})
            setattr(oe, name, mod)
            spec.loader.exec_module(mod)
        tasks = types.ModuleType("oe.spdx30_tasks")
        tasks._get_cves_info = lambda d: iter(STATUSES)
        oe.spdx30_tasks = tasks
        Modules(self, {"oe.spdx30_tasks": tasks})
        self.oe = oe

        class D:
            values = {"PN": "shadow", "SPDX_UUID_NAMESPACE": "sbom.openembedded.org",
                      "SPDX_NAMESPACE_PREFIX": "http://spdx.org/spdxdocs",
                      "SPDX_PACKAGE_SUPPLIER": "", "SPDX_ORGANIZATION": "",
                      "PACKAGE_ARCH": "core2-64", "SSTATE_PKGARCH": "core2-64",
                      "BB_UNIHASH": "0" * 64, "SOURCE_DATE_EPOCH": "0",
                      "SPDX_TOOL_NAME": "oe-spdx-creator", "SPDX_TOOL_VERSION": "1.0",
                      "SPDX_AUTHORS": "", "SPDX_VERSION": "3.0.1"}

            def getVar(self, name, expand=True):
                return self.values.get(name)

            def expand(self, s):
                return s
        self.d = D()

    def test_the_real_objects_carry_the_notes(self):
        install_function()()
        sbom30 = self.oe.sbom30
        build = sbom30.ObjectSet.new_objset(self.d, "recipe-shadow", copy_from_bitbake_doc=False)
        pkgs = []
        for name in ("shadow", "shadow-base"):
            objset = sbom30.ObjectSet.new_objset(self.d, "package-" + name, copy_from_bitbake_doc=False)
            pkg = objset.add_root(self.oe.spdx30.software_Package(
                _id=objset.new_spdxid("package", name), creationInfo=objset.doc.creationInfo, name=name))
            pkgs.append((objset, sbom30.get_element_link_id(pkg)))
        self.assertEqual(create_spdx_vex(self.oe, self.d, build, pkgs),
                         {c: {n} for c, n in EXPECTED.items()})


class InheritedTests(unittest.TestCase):
    """Both stacks, or a scan on a feed build rebuilds every SPDX document."""

    def inherits(self, name):
        return [l.strip() for l in (FEATURE / name).read_text().splitlines()
                if l.strip().startswith("INHERIT") and "avocado-spdx-vex-notes" in l]

    def test_feed_and_scan_inherit_it(self):
        for name in ("sbom.yml", "cve-check.yml"):
            with self.subTest(fragment=name):
                self.assertEqual(self.inherits(name), ['INHERIT += "avocado-spdx-vex-notes"'])


if __name__ == "__main__":
    unittest.main()
