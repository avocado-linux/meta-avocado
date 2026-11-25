#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""Feed scope on scarthgap: one package document per recipe, and an alternate
kernel kept on its own build.

scarthgap's create-spdx-3.0 has no recipe-level package, so do_feed_sbom roots
the feed document at one package document of each recipe. Both kernels of a
multi-kernel machine write their documents under the same names and carry the
same identity aliases, so the alternate kernel's documents get aliases of their
own (avocado_sbom.spdxalias) before they are deserialized.

RealLibTest writes a default tree and an alternate multiconfig's tree with
scarthgap OE-core's own oe.sbom30, runs the recipe's do_feed_sbom on them and
reads the document it writes; it runs when OE_CORE_LIB names scarthgap
OE-core's meta/lib. test_spdxalias.py covers avocado_sbom.spdxalias on its own.

  cd meta-avocado-sbom/tests && PYTHONPATH=../lib python3 -m unittest discover -p 'test_*.py'
"""

import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import types
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "lib"))

from avocado_sbom import feedcheck, feedsbom, report, spdxalias  # noqa: E402

RECIPE = HERE.parent / "recipes-avocado" / "avocado-cve-report" / "avocado-cve-report.bb"

def recipe_python(name):
    """The body of the recipe's python task name, as source."""
    text = RECIPE.read_text()
    m = re.search(r"^python %s\(\) \{\n(.*?)^\}\n" % name, text, re.M | re.S)
    assert m, "%s is gone from the recipe" % name
    return textwrap.dedent(m.group(1))


def recipe_functions():
    """Every top-level def avocado_feed_* of the recipe, as source."""
    text = RECIPE.read_text() + "\n#"
    found = re.findall(r"^(def avocado_feed_\w+\(.*?)(?=^\S)", text, re.M | re.S)
    assert found, "no avocado_feed_ functions in the recipe"
    return "\n".join(found)


class Modules:
    """Put modules in sys.modules for the duration of a test."""

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


class Fatal(Exception):
    pass


class D:
    """The slice of a bitbake datastore the feed task and oe.sbom30 read."""

    def __init__(self, values):
        self.values = dict(values)

    def getVar(self, name, expand=True):
        return self.values.get(name)

    def setVar(self, name, value):
        self.values[name] = value

    def getVarFlag(self, name, flag):
        return None

    def expand(self, s):
        return s


MACHINE = "avocado-raspberrypi5"
MC = "raspberrypi-6_6"
ARCHS = "allarch cortexa76 raspberrypi5 x86_64"

KERNEL_CPE = "cpe:2.3:o:linux:linux_kernel:%s:*:*:*:*:*:*:*"
# Compiled sources of the two kernels. init/main.c passes the scanner's check
# that a kernel's list is real.
DEFAULT_SOURCES = ("init/main.c", "kernel/fork.c")
ALT_SOURCES = ("init/main.c", "drivers/only66.c")
# 2001 is fixed in a file only the 6.6 kernel compiles, 2002 in one only the
# 6.12 kernel compiles.
RECORDS = (("CVE-2026-2001", ["drivers/only66.c"]), ("CVE-2026-2002", ["kernel/fork.c"]))


def scanner():
    tool = os.environ.get("SBOM_CVE_CHECK")
    return tool if tool and os.access(tool, os.X_OK) else None


def cve_record(cve, program_files, product="linux_kernel", less_than="6.18.99"):
    """A cvelistV5 record: product below less_than affected, its fix in
    program_files."""
    vendor = "linux" if product == "linux_kernel" else product
    return {
        "dataType": "CVE_RECORD", "dataVersion": "5.1",
        "cveMetadata": {"cveId": cve, "state": "PUBLISHED",
                        "datePublished": "2026-01-01T00:00:00.000Z",
                        "dateUpdated": "2026-01-01T00:00:00.000Z"},
        "containers": {"cna": {
            "providerMetadata": {"orgId": "00000000-0000-0000-0000-000000000000",
                                 "dateUpdated": "2026-01-01T00:00:00.000Z"},
            "descriptions": [{"lang": "en", "value": "test record %s" % cve}],
            "affected": [{
                "vendor": vendor, "product": product,
                "cpes": ["cpe:2.3:o:%s:%s:*:*:*:*:*:*:*:*" % (vendor, product)],
                "defaultStatus": "unaffected",
                "versions": [{"version": "0", "lessThan": less_than, "status": "affected",
                              "versionType": "semver"}],
                "programFiles": list(program_files),
            }],
        }},
    }



@unittest.skipUnless(os.environ.get("OE_CORE_LIB"),
                     "set OE_CORE_LIB to scarthgap OE-core's meta/lib to run against it")
class RealLibTest(unittest.TestCase):
    def setUp(self):
        lib = Path(os.environ["OE_CORE_LIB"])
        bb = types.ModuleType("bb")
        bb.warn = bb.note = bb.debug = bb.plain = lambda *a, **k: None

        def fatal(msg):
            raise Fatal(msg)
        bb.fatal = fatal

        def remove(path):
            if os.path.lexists(path):
                os.remove(path)
        bb.utils = types.SimpleNamespace(
            remove=remove, mkdirhier=lambda p: os.makedirs(p, exist_ok=True),
            sha256_file=lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest())
        bb.data = types.SimpleNamespace(createCopy=lambda d: D(d.values))
        oe = types.ModuleType("oe")
        oe.__path__ = []
        mods = {"bb": bb, "oe": oe}
        for name in ("packagedata", "cve_check"):
            mods["oe." + name] = types.ModuleType("oe." + name)
            setattr(oe, name, mods["oe." + name])
        Modules(self, mods)
        for name in ("spdx30", "spdx_common", "sbom30"):
            spec = importlib.util.spec_from_file_location("oe." + name, lib / "oe" / (name + ".py"))
            mod = importlib.util.module_from_spec(spec)
            Modules(self, {"oe." + name: mod})
            setattr(oe, name, mod)
            spec.loader.exec_module(mod)
        self.bb, self.oe = bb, oe

        self.top = Path(tempfile.mkdtemp(prefix="feed-scarthgap-"))
        self.addCleanup(shutil.rmtree, self.top)
        self.tmp = self.top / "tmp"
        self.alt_tmp = self.top / ("tmp-" + MC)
        self.base = {
            "SPDX_UUID_NAMESPACE": "sbom.openembedded.org",
            "SPDX_NAMESPACE_PREFIX": "http://spdx.org/spdxdocs",
            "SPDX_TOOL_NAME": "oe-spdx-creator", "SPDX_TOOL_VERSION": "1.0",
            "SPDX_AUTHORS": "openembedded",
            "SPDX_AUTHORS_openembedded_name": "OpenEmbedded",
            "SPDX_AUTHORS_openembedded_type": "organization",
            "SPDX_VERSION": "3.0.1", "SOURCE_DATE_EPOCH": "0",
            "SPDX_PROFILES": "core build software simpleLicensing security",
            "SPDX_MULTILIB_SSTATE_ARCHS": ARCHS, "BB_CURRENTTASK": "create_spdx",
        }

    # --- writing trees the way create-spdx-3.0 does -------------------------

    def datastore(self, tmp, pn, unihash, arch="raspberrypi5"):
        return D(dict(self.base, PN=pn, BB_UNIHASH=unihash, SSTATE_PKGARCH=arch,
                      DEPLOY_DIR_SPDX=str(tmp / "deploy" / "spdx")))

    def write_bitbake(self, tmp):
        sbom30 = self.oe.sbom30
        d = self.datastore(tmp, "bitbake", "b" * 64)
        objset = sbom30.ObjectSet.new_objset(d, "bitbake", False)
        sbom30.write_jsonld_doc(d, objset, tmp / "deploy" / "spdx" / "bitbake.spdx.json")

    def write_recipe(self, tmp, pn, version, unihash, packages, cves=(), deps=(),
                     arch="raspberrypi5", link_build=True, cpe=None, sources=None):
        """recipes/recipe-<pn> and packages-staging/package-<name>, as
        scarthgap's create_spdx writes them: the build and the CVE elements in
        the recipe document, each package naming them by alias. sources are
        the build's compiled source files, as the source walk keeps them under
        SPDX_INCLUDE_COMPILED_SOURCES."""
        sbom30, spdx30 = self.oe.sbom30, self.oe.spdx30
        d = self.datastore(tmp, pn, unihash, arch)
        deploy = Path(d.getVar("DEPLOY_DIR_SPDX"))
        build_objset = sbom30.ObjectSet.new_objset(d, "recipe-" + pn)
        build = build_objset.new_task_build("recipe", "recipe")
        build_objset.set_element_alias(build)
        build_objset.doc.rootElement.append(build)
        vulns = []
        notes = {}
        for cve in cves:
            # (CVE, status notes) as avocado-spdx-vex-notes writes them.
            cve, notes[cve] = cve if isinstance(cve, tuple) else (cve, None)
            v = build_objset.new_cve_vuln(cve)
            build_objset.set_element_alias(v)
            vulns.append(v)
        for dep in deps:
            build_objset.new_scoped_relationship(
                [build], spdx30.RelationshipType.dependsOn, spdx30.LifecycleScopeType.build, [dep])
        if sources:
            workdir = Path(tmp) / "work" / pn
            files = []
            for i, name in enumerate(sources, 1):
                path = workdir / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("%s %s %s\n" % (tmp, pn, name))
                files.append(build_objset.new_file(
                    build_objset.new_spdxid("sourcefile", str(i)), name, path,
                    purposes=[spdx30.software_SoftwarePurpose.source]))
            build_objset.new_scoped_relationship(
                [build], spdx30.RelationshipType.hasInput, spdx30.LifecycleScopeType.build,
                sorted(files, key=lambda f: f._id))
        for name in packages:
            pkg_objset = sbom30.ObjectSet.new_objset(d, "package-" + name)
            pkg = pkg_objset.add_root(spdx30.software_Package(
                _id=pkg_objset.new_spdxid("package", name),
                creationInfo=pkg_objset.doc.creationInfo, name=name,
                software_packageVersion=version,
                software_primaryPurpose=spdx30.software_SoftwarePurpose.install))
            pkg.externalIdentifier.append(spdx30.ExternalIdentifier(
                externalIdentifierType=spdx30.ExternalIdentifierType.cpe23,
                identifier=cpe or "cpe:2.3:*:*:%s:%s:*:*:*:*:*:*:*" % (pn, version)))
            if link_build:
                pkg_objset.new_scoped_relationship(
                    [sbom30.get_element_link_id(build)], spdx30.RelationshipType.hasOutput,
                    spdx30.LifecycleScopeType.build, [pkg])
            for v, cve in zip(vulns, notes):
                for rel in pkg_objset.new_vex_patched_relationship(
                        [sbom30.get_element_link_id(v)], [pkg]):
                    if notes[cve]:
                        rel.security_statusNotes = notes[cve]
            if vulns:
                pkg_objset.new_relationship(
                    [pkg], spdx30.RelationshipType.hasAssociatedVulnerability,
                    sorted(sbom30.get_element_link_id(v) for v in vulns))
            sbom30.write_recipe_jsonld_doc(d, pkg_objset, "packages-staging", deploy,
                                           create_spdx_id_links=False)
        sbom30.write_recipe_jsonld_doc(d, build_objset, "recipes", deploy)
        return sbom30.get_element_link_id(build)

    def write_pkgdata(self, tmp, pn, version, packages):
        reverse = tmp / "pkgdata" / "raspberrypi5" / "runtime-reverse"
        reverse.mkdir(parents=True, exist_ok=True)
        for name in packages:
            (reverse / name).write_text("PN: %s\nPV: %s\nPKGV: %s\nPKGR: r0\n"
                                        % (pn, version, version))

    def build_trees(self, alt=True, alt_cves=("CVE-2024-0001", "CVE-2023-9999"), link_build=True):
        for tmp in (self.tmp, self.alt_tmp) if alt else (self.tmp,):
            self.write_bitbake(tmp)
        openssl = self.write_recipe(self.tmp, "openssl-native", "3.2.6", "1" * 64, [],
                                    arch="x86_64")
        self.write_recipe(self.tmp, "linux-raspberrypi", "6.12.47", "2" * 64,
                          ["kernel", "kernel-module-a"], ["CVE-2024-0001", "CVE-2024-0002"],
                          [openssl])
        self.write_pkgdata(self.tmp, "linux-raspberrypi", "6.12.47", ["kernel", "kernel-module-a"])
        self.write_recipe(self.tmp, "busybox", "1.36.1", "3" * 64,
                          ["busybox-syslog", "busybox"], ["CVE-2026-38752"], arch="cortexa76")
        self.write_pkgdata(self.tmp, "busybox", "1.36.1", ["busybox", "busybox-syslog"])
        # Shipped, but nospdx: no document at all.
        self.write_pkgdata(self.tmp, "packagegroup-core-boot", "1.0", ["packagegroup-core-boot"])
        if alt:
            # The same PN and document names at another version and task hash,
            # depending on a recipe only the default tree's documents describe.
            self.write_recipe(self.alt_tmp, "linux-raspberrypi", "6.6.63", "4" * 64,
                              ["kernel", "kernel-module-a-6.6.63"],
                              alt_cves, [openssl], link_build=link_build)
            self.write_pkgdata(self.alt_tmp, "linux-raspberrypi", "6.6.63",
                               ["kernel", "kernel-module-a-6.6.63"])

    # --- running the recipe's task ------------------------------------------

    def run_feed_sbom(self, alt=True, mc_recipes=None):
        deploy = self.tmp / "deploy"
        feed_dir = deploy / "avocado-cve"
        name = "avocado-feed-raspberrypi5"
        d = D(dict(
            self.base, PN="avocado-cve-report", BB_UNIHASH="5" * 64,
            SSTATE_PKGARCH="raspberrypi5", MACHINE=MACHINE,
            TOPDIR=str(self.top), TMPDIR=str(self.tmp),
            DEPLOY_DIR_SPDX=str(deploy / "spdx"),
            PKGDATA_DIR=str(self.tmp / "pkgdata" / "raspberrypi5"),
            AVOCADO_FEED_SBOM_DIR=str(feed_dir), AVOCADO_FEED_SBOM_NAME=name,
            AVOCADO_FEED_SBOM_FILE=str(feed_dir / (name + ".spdx.json")),
            AVOCADO_FEED_COVERAGE_FILE=str(feed_dir / (name + ".coverage.json")),
            AVOCADO_CVE_REPORT_FILE=str(feed_dir / ("avocado-cve-report-%s.json" % MACHINE)),
            AVOCADO_RPM_MANIFEST_FILE=str(feed_dir / ("avocado-rpm-manifest-%s.json" % MACHINE)),
            AVOCADO_FEED_SBOM_MAX_MISSING="33",
            AVOCADO_MULTIKERNEL_MC_RECIPES=(mc_recipes or "%s:linux-raspberrypi" % MC) if alt else "",
        ))
        ns = {"bb": self.bb, "os": os, "d": d}
        exec(recipe_functions(), ns)
        exec("def do_feed_sbom(d):\n" + textwrap.indent(recipe_python("do_feed_sbom"), "    "), ns)
        ns["do_feed_sbom"](d)
        with open(d.getVar("AVOCADO_FEED_SBOM_FILE")) as f:
            document = json.load(f)
        with open(d.getVar("AVOCADO_FEED_COVERAGE_FILE")) as f:
            coverage = json.load(f)
        return document, coverage

    @staticmethod
    def graph(document):
        return {n["spdxId"]: n for n in document["@graph"] if "spdxId" in n}

    def builds_of(self, document):
        """{(package name, version): build name} through hasOutput."""
        nodes = self.graph(document)
        found = {}
        for n in nodes.values():
            if n.get("relationshipType") != "hasOutput":
                continue
            for t in n["to"]:
                pkg = nodes[t]
                found.setdefault((pkg["name"], pkg["software_packageVersion"]), set()).add(n["from"])
        return {k: sorted(nodes[b]["name"] + "@" + b.split("/")[-3][:1] for b in v)
                for k, v in found.items()}

    def cves_of(self, document):
        """{(package name, version): CVE ids} through the VEX statements, with
        the task hash of the document each CVE element came from."""
        nodes = self.graph(document)
        found = {}
        for n in nodes.values():
            if not n.get("type", "").startswith("security_Vex"):
                continue
            vuln = nodes[n["from"]]
            cve = vuln["externalIdentifier"][0]["identifier"]
            for t in n["to"]:
                pkg = nodes[t]
                found.setdefault((pkg["name"], pkg["software_packageVersion"]), set()).add(
                    (cve, vuln["spdxId"].split("/")[-3][:1]))
        return found

    # --- the tests ----------------------------------------------------------

    def test_one_package_document_per_recipe(self):
        self.build_trees(alt=False)
        document, coverage = self.run_feed_sbom(alt=False)
        sbom, = [n for n in document["@graph"] if n.get("type") == "software_Sbom"]
        nodes = self.graph(document)
        self.assertEqual(sorted(nodes[r]["name"] for r in sbom["rootElement"]),
                         ["busybox", "kernel"])
        self.assertEqual(coverage["roots"], 2)
        self.assertEqual(coverage["no_document"], ["packagegroup-core-boot"])
        packages = sorted(n["name"] for n in nodes.values() if n.get("type") == "software_Package")
        self.assertEqual(packages, ["busybox", "kernel"])
        self.assertEqual(self.builds_of(document), {
            ("busybox", "1.36.1"): ["busybox:do_create_spdx:recipe@3"],
            ("kernel", "6.12.47"): ["linux-raspberrypi:do_create_spdx:recipe@2"],
        })

    def test_alternate_kernel_keeps_its_own_build_and_cves(self):
        self.build_trees()
        document, coverage = self.run_feed_sbom()
        self.assertEqual(coverage["alt_included"], ["%s:linux-raspberrypi" % MC])
        self.assertEqual(coverage["alt_not_covered"], [])
        self.assertEqual(coverage["roots"], 3)
        builds = self.builds_of(document)
        self.assertEqual(builds[("kernel", "6.12.47")], ["linux-raspberrypi:do_create_spdx:recipe@2"])
        self.assertEqual(builds[("kernel", "6.6.63")], ["linux-raspberrypi:do_create_spdx:recipe@4"])
        cves = self.cves_of(document)
        self.assertEqual(cves[("kernel", "6.12.47")], {("CVE-2024-0001", "2"), ("CVE-2024-0002", "2")})
        self.assertEqual(cves[("kernel", "6.6.63")], {("CVE-2024-0001", "4"), ("CVE-2023-9999", "4")})

    def test_alternate_kernel_links_to_shared_recipes_by_their_own_aliases(self):
        self.build_trees()
        document, _coverage = self.run_feed_sbom()
        nodes = self.graph(document)
        deps = {nodes[n["from"]]["name"]: [nodes[t]["name"] for t in n["to"]]
                for n in nodes.values() if n.get("relationshipType") == "dependsOn"}
        self.assertEqual(deps.get("linux-raspberrypi:do_create_spdx:recipe"),
                         ["openssl-native:do_create_spdx:recipe"])
        builds = [n for n in nodes.values() if n.get("type") == "build_Build"
                  and n["name"].startswith("linux-raspberrypi")]
        self.assertEqual(len(builds), 2)
        openssl, = [n["spdxId"] for n in nodes.values() if n.get("type") == "build_Build"
                    and n["name"].startswith("openssl-native")]
        for build in builds:
            dep = [n for n in nodes.values() if n.get("relationshipType") == "dependsOn"
                   and n["from"] == build["spdxId"]]
            self.assertEqual([d["to"] for d in dep], [[openssl]], build["spdxId"])

    def test_feedcheck_accepts_the_document(self):
        self.build_trees()
        self.run_feed_sbom()
        paths = feedcheck.Paths(str(self.tmp), MACHINE)
        for check in (feedcheck.check_document_exists, feedcheck.check_document_jsonld,
                      feedcheck.check_document_roots, feedcheck.check_coverage_record):
            name, ok, detail = check(paths)
            self.assertTrue(ok, "%s: %s" % (name, detail))

    def test_without_its_own_aliases_the_alternate_kernel_is_dropped(self):
        # The collision the qualification prevents: both kernels' documents
        # carry the same aliases, and the packages name their build and CVEs by
        # them in "from".
        self.build_trees()
        real = spdxalias.multiconfig_map
        spdxalias.multiconfig_map = lambda aliases, mc: {}
        self.addCleanup(setattr, spdxalias, "multiconfig_map", real)
        document, coverage = self.run_feed_sbom()
        self.assertEqual(coverage["alt_included"], [])
        reasons = [e["reason"] for e in coverage["alt_not_covered"]]
        self.assertEqual(len(reasons), 1)
        self.assertTrue(reasons[0].startswith("alias collision: "), reasons)
        self.assertEqual(self.builds_of(document),
                         {("busybox", "1.36.1"): ["busybox:do_create_spdx:recipe@3"],
                          ("kernel", "6.12.47"): ["linux-raspberrypi:do_create_spdx:recipe@2"]})

    def test_a_shared_build_alias_alone_is_a_collision(self):
        # With no CVE in common the build is the only shared alias, and the
        # package names it in "from".
        self.build_trees(alt_cves=("CVE-2023-9999",))
        real = spdxalias.multiconfig_map
        spdxalias.multiconfig_map = lambda aliases, mc: {}
        self.addCleanup(setattr, spdxalias, "multiconfig_map", real)
        _document, coverage = self.run_feed_sbom()
        reasons = [e["reason"] for e in coverage["alt_not_covered"]]
        self.assertEqual(len(reasons), 1)
        self.assertTrue(reasons[0].startswith("alias collision: "), reasons)

    def test_a_kernel_package_with_no_build_is_dropped(self):
        # The scanner names an entry after the build, so a package that names
        # none cannot be scanned as that kernel.
        self.build_trees(link_build=False)
        document, coverage = self.run_feed_sbom()
        self.assertEqual(coverage["alt_included"], [])
        reasons = [e["reason"] for e in coverage["alt_not_covered"]]
        self.assertEqual(len(reasons), 1)
        self.assertTrue(reasons[0].startswith("reference collision: "), reasons)
        self.assertNotIn(("kernel", "6.6.63"), self.builds_of(document))

    def test_a_shared_build_drops_the_alternate_kernel(self):
        # Past the alias check, the build check: a package bound to the other
        # kernel's build is a wrong reference.
        self.build_trees()
        from avocado_sbom import feedsbom
        saved = (spdxalias.multiconfig_map, feedsbom.drop_alias_collided)
        spdxalias.multiconfig_map = lambda aliases, mc: {}
        feedsbom.drop_alias_collided = lambda included, shared, targets: (included, [])

        def restore():
            spdxalias.multiconfig_map, feedsbom.drop_alias_collided = saved
        self.addCleanup(restore)
        document, coverage = self.run_feed_sbom()
        self.assertEqual(coverage["alt_included"], [])
        reasons = [e["reason"] for e in coverage["alt_not_covered"]]
        self.assertEqual(len(reasons), 1)
        self.assertTrue(reasons[0].startswith("reference collision: "), reasons)
        builds = self.builds_of(document)
        self.assertEqual(builds[("kernel", "6.12.47")], ["linux-raspberrypi:do_create_spdx:recipe@2"])
        self.assertNotIn(("kernel", "6.6.63"), builds)

    def test_a_collision_in_one_multiconfig_keeps_the_other(self):
        # Two alternate multiconfigs build the recipe (Jetson builds
        # nvidia-kernel-oot in three). Only the bad one's documents keep the
        # default's aliases, so only its packages land on another build.
        self.build_trees()
        good, bad = MC, "other-mc"
        bad_tmp = self.top / ("tmp-" + bad)
        self.write_bitbake(bad_tmp)
        self.write_recipe(bad_tmp, "linux-raspberrypi", "6.1.99", "6" * 64,
                          ["kernel", "kernel-module-a-6.1.99"], ["CVE-2022-0001"])
        self.write_pkgdata(bad_tmp, "linux-raspberrypi", "6.1.99",
                           ["kernel", "kernel-module-a-6.1.99"])
        from avocado_sbom import feedsbom
        saved = (spdxalias.multiconfig_map, feedsbom.drop_alias_collided)
        spdxalias.multiconfig_map = (
            lambda aliases, mc: {} if mc == bad else saved[0](aliases, mc))
        feedsbom.drop_alias_collided = lambda included, shared, targets: (included, [])

        def restore():
            spdxalias.multiconfig_map, feedsbom.drop_alias_collided = saved
        self.addCleanup(restore)
        document, coverage = self.run_feed_sbom(
            mc_recipes="%s:linux-raspberrypi %s:linux-raspberrypi" % (good, bad))
        self.assertEqual(coverage["alt_included"], ["%s:linux-raspberrypi" % good])
        self.assertEqual([(e["mc"], e["reason"].split(":")[0])
                          for e in coverage["alt_not_covered"]],
                         [(bad, "reference collision")])
        builds = self.builds_of(document)
        self.assertEqual(builds[("kernel", "6.12.47")], ["linux-raspberrypi:do_create_spdx:recipe@2"])
        self.assertEqual(builds[("kernel", "6.6.63")], ["linux-raspberrypi:do_create_spdx:recipe@4"])
        self.assertNotIn(("kernel", "6.1.99"), builds)

    # --- the kernel CVE filter, VEX overlap, unresolved alternate links -----

    def kernel_trees(self, alt_mc=MC, alt_pn="linux-raspberrypi", alt_version="6.6.63",
                     alt_cves=("CVE-2024-0001",), default_cves=("CVE-2024-0001",),
                     alt_deps=(), alt_pv=None, busybox_cpe=None, busybox_sources=None):
        """A default kernel and an alternate one, both linux_kernel by CPE and
        both listing their compiled sources, with busybox beside them."""
        alt_tmp = self.top / ("tmp-" + alt_mc)
        for tmp in (self.tmp, alt_tmp):
            self.write_bitbake(tmp)
        openssl = self.write_recipe(self.tmp, "openssl-native", "3.2.6", "1" * 64, [],
                                    arch="x86_64")
        self.write_recipe(self.tmp, "linux-raspberrypi", "6.12.47", "2" * 64,
                          ["kernel", "kernel-module-a"], default_cves, [openssl],
                          cpe=KERNEL_CPE % "6.12.47", sources=DEFAULT_SOURCES)
        self.write_pkgdata(self.tmp, "linux-raspberrypi", "6.12.47", ["kernel", "kernel-module-a"])
        self.write_recipe(self.tmp, "busybox", "1.36.1", "3" * 64, ["busybox"],
                          ["CVE-2026-38752"], arch="cortexa76", cpe=busybox_cpe,
                          sources=busybox_sources)
        self.write_pkgdata(self.tmp, "busybox", "1.36.1", ["busybox"])
        self.alt_kernel_build = self.write_recipe(alt_tmp, alt_pn, alt_pv or alt_version, "4" * 64,
                          ["kernel", "kernel-module-a-" + alt_version], alt_cves,
                          [openssl] + list(alt_deps), cpe=KERNEL_CPE % alt_version,
                          sources=ALT_SOURCES)
        self.write_pkgdata(alt_tmp, alt_pn, alt_pv or alt_version,
                           ["kernel", "kernel-module-a-" + alt_version])
        return "%s:%s" % (alt_mc, alt_pn)

    def sources_of(self, document):
        """{root package version: compiled source names} as the scanner reads
        them: the build that has the package as output (hasOutput, scope
        build), that build's hasInput source files."""
        nodes = self.graph(document)
        found = {}
        for n in nodes.values():
            if (n.get("relationshipType") != "hasOutput" or n.get("scope") != "build"
                    or nodes[n["from"]].get("type") != "build_Build"):
                continue
            for t in n["to"]:
                pkg = nodes.get(t, {})
                if pkg.get("type") != "software_Package":
                    continue
                found[pkg["software_packageVersion"]] = sorted(
                    nodes[f]["name"] for r in nodes.values()
                    if r.get("relationshipType") == "hasInput" and r["from"] == n["from"]
                    for f in r["to"]
                    if nodes.get(f, {}).get("software_primaryPurpose") == "source")
        return found

    def test_each_kernel_reaches_the_scan_with_its_own_compiled_sources(self):
        mc_recipes = self.kernel_trees()
        document, coverage = self.run_feed_sbom(mc_recipes=mc_recipes)
        self.assertEqual(coverage["alt_included"], [mc_recipes])
        self.assertEqual(self.sources_of(document), {
            "6.12.47": sorted(DEFAULT_SOURCES), "6.6.63": sorted(ALT_SOURCES),
            "1.36.1": []})

    def test_an_alternate_with_other_statements_is_left_out(self):
        mc_recipes = self.kernel_trees(alt_mc="jetson-rt", alt_pn="linux-yocto-rt",
                                       alt_version="6.12.47",
                                       alt_cves=("CVE-2024-0001", "CVE-2026-1003"))
        document, coverage = self.run_feed_sbom(mc_recipes=mc_recipes)
        self.assertEqual(coverage["alt_included"], [])
        self.assertEqual(coverage["alt_not_covered"], [{
            "mc": "jetson-rt", "recipe": "linux-yocto-rt",
            "reason": "VEX overlap: linux_kernel 6.12.47 is also linux-raspberrypi, "
                      "with other statements"}])
        self.assertNotIn("CVE-2026-1003", json.dumps(document))

    def test_a_statement_differing_in_notes_only_counts_as_other(self):
        mc_recipes = self.kernel_trees(alt_mc="jetson-rt", alt_pn="linux-yocto-rt",
                                       alt_version="6.12.47",
                                       alt_cves=[("CVE-2024-0001", "backported-patch")],
                                       default_cves=[("CVE-2024-0001", "fixed-version")])
        _document, coverage = self.run_feed_sbom(mc_recipes=mc_recipes)
        self.assertEqual([e["recipe"] for e in coverage["alt_not_covered"]], ["linux-yocto-rt"])

    def test_the_cpe_version_alone_overlaps(self):
        # Another package version, the same CPE version: the scanner matches
        # statements on either.
        mc_recipes = self.kernel_trees(alt_mc="jetson-rt", alt_pn="linux-yocto-rt",
                                       alt_version="6.12.47", alt_pv="6.12.47-rt",
                                       alt_cves=("CVE-2024-0001", "CVE-2026-1003"))
        _document, coverage = self.run_feed_sbom(mc_recipes=mc_recipes)
        self.assertEqual([e["recipe"] for e in coverage["alt_not_covered"]], ["linux-yocto-rt"])

    def test_a_module_of_a_kernel_left_out_is_left_out_too(self):
        # The RT kernel goes on VEX overlap; a module built for it in the same
        # multiconfig then links to a build no loaded document defines.
        self.kernel_trees(alt_mc="jetson-rt", alt_pn="linux-yocto-rt", alt_version="6.12.47",
                          alt_cves=("CVE-2024-0001", "CVE-2026-1003"))
        alt_tmp = self.top / "tmp-jetson-rt"
        self.write_recipe(alt_tmp, "rt-module", "1.0", "c" * 64, ["kernel-module-rt"],
                          deps=[self.alt_kernel_build])
        self.write_pkgdata(alt_tmp, "rt-module", "1.0", ["kernel-module-rt"])
        _document, coverage = self.run_feed_sbom(
            mc_recipes="jetson-rt:linux-yocto-rt jetson-rt:rt-module")
        self.assertEqual(coverage["alt_included"], [])
        reasons = {e["recipe"]: e["reason"].split(":")[0] for e in coverage["alt_not_covered"]}
        self.assertEqual(reasons, {"linux-yocto-rt": "VEX overlap",
                                   "rt-module": "unresolved reference"})
        self.assertEqual(coverage["unresolved_ids"], 0)

    def test_an_alternate_with_the_same_statements_stays(self):
        mc_recipes = self.kernel_trees(alt_mc="jetson-rt", alt_pn="linux-yocto-rt",
                                       alt_version="6.12.47")
        _document, coverage = self.run_feed_sbom(mc_recipes=mc_recipes)
        self.assertEqual(coverage["alt_included"], [mc_recipes])
        self.assertEqual(coverage["alt_not_covered"], [])

    def test_a_link_only_the_alternate_multiconfig_resolves_leaves_that_kernel_out(self):
        alt_tmp = self.top / ("tmp-" + MC)
        self.write_bitbake(alt_tmp)
        only_here = self.write_recipe(alt_tmp, "rt-only-tool-native", "1.0", "7" * 64, [],
                                      arch="x86_64")
        mc_recipes = self.kernel_trees(alt_deps=[only_here])
        document, coverage = self.run_feed_sbom(mc_recipes=mc_recipes)
        self.assertEqual(coverage["alt_included"], [])
        entry, = coverage["alt_not_covered"]
        self.assertEqual((entry["mc"], entry["recipe"]), (MC, "linux-raspberrypi"))
        self.assertTrue(entry["reason"].startswith("unresolved reference: "), entry)
        self.assertEqual(coverage["unresolved_ids"], 0)
        self.assertEqual(sorted(self.sources_of(document)), ["1.36.1", "6.12.47"])

    def test_a_module_of_a_kernel_left_out_never_finds_the_default_kernel(self):
        # The 6.6 kernel goes on an unresolved link; its module names its build
        # by the same alias as the default kernel's, which must not catch it.
        alt_tmp = self.top / ("tmp-" + MC)
        self.write_bitbake(alt_tmp)
        only_here = self.write_recipe(alt_tmp, "rt-only-tool-native", "1.0", "7" * 64, [],
                                      arch="x86_64")
        mc_recipes = self.kernel_trees(alt_deps=[only_here])
        self.write_recipe(alt_tmp, "rpi-module", "1.0", "c" * 64, ["kernel-module-x"],
                          deps=[self.alt_kernel_build])
        self.write_pkgdata(alt_tmp, "rpi-module", "1.0", ["kernel-module-x"])
        _document, coverage = self.run_feed_sbom(mc_recipes=mc_recipes + " %s:rpi-module" % MC)
        self.assertEqual(coverage["alt_included"], [])
        self.assertEqual(sorted(e["recipe"] for e in coverage["alt_not_covered"]),
                         ["linux-raspberrypi", "rpi-module"])

    def test_a_module_of_a_kernel_without_its_package_document_is_left_out_too(self):
        # The 6.6 kernel has its build document but no package document, so it
        # is not covered; a module linking to its build must not find the
        # default kernel's build under the same alias.
        alt_tmp = self.top / ("tmp-" + MC)
        mc_recipes = self.kernel_trees()
        for doc in (alt_tmp / "deploy" / "spdx").glob("*/packages-staging/package-kernel*.spdx.json"):
            doc.unlink()
        self.write_recipe(alt_tmp, "rpi-module", "1.0", "c" * 64, ["kernel-module-x"],
                          deps=[self.alt_kernel_build])
        self.write_pkgdata(alt_tmp, "rpi-module", "1.0", ["kernel-module-x"])
        _document, coverage = self.run_feed_sbom(mc_recipes=mc_recipes + " %s:rpi-module" % MC)
        self.assertEqual(coverage["alt_included"], [])
        self.assertEqual(sorted(e["recipe"] for e in coverage["alt_not_covered"]),
                         ["linux-raspberrypi", "rpi-module"])

    def scan(self, records=()):
        """{(entry name, version): {CVE: (status, detail)}} from sbom-cve-check
        run on the feed document against a cvelist database of the RECORDS and
        records, cve_record arguments."""
        db = self.top / "cvelist"
        for args in tuple(RECORDS) + tuple(records):
            cve = args[0]
            year, number = cve.split("-")[1:]
            path = db / "cves" / year / (number[:-3] + "xxx") / (cve + ".json")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(cve_record(*args)))
        git = ["git", "-C", str(db), "-c", "user.name=t", "-c", "user.email=t@t",
               "-c", "commit.gpgsign=false"]
        subprocess.run(git[:3] + ["init", "-q"], check=True)
        subprocess.run(git + ["add", "-A"], check=True)
        subprocess.run(git + ["commit", "-q", "-m", "records"], check=True)
        out = self.scan_path = self.top / "scan.yocto.json"
        document = self.tmp / "deploy" / "avocado-cve" / "avocado-feed-raspberrypi5.spdx.json"
        subprocess.run(
            [scanner(), "--sbom-path", str(document), "--disable-auto-updates",
             "--ignore-default-config", "--offline-mode",
             "--no-builtin-products-db", "--export-process-native",
             "--add-db", "cve-db-cvelist", str(db), "offline_mode=true",
             "--export-type", "yocto-cve-check-manifest", "--export-path", str(out)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        return {(e["name"], e["version"]): {i["id"]: (i["status"], i.get("detail"))
                                           for i in e["issue"]}
                for e in json.loads(out.read_text())["package"]}

    @unittest.skipUnless(scanner(), "set SBOM_CVE_CHECK to sbom-cve-check 1.4.0 to scan")
    def test_the_scan_filters_each_kernel_on_its_own_sources(self):
        mc_recipes = self.kernel_trees()
        self.run_feed_sbom(mc_recipes=mc_recipes)
        result = self.scan()
        default = next(v for (n, ver), v in result.items() if ver == "6.12.47")
        alt = next(v for (n, ver), v in result.items() if ver == "6.6.63")
        self.assertEqual(default["CVE-2026-2001"], ("Ignored", "not-applicable-config"))
        self.assertEqual(default["CVE-2026-2002"][0], "Unpatched")
        self.assertEqual(alt["CVE-2026-2001"][0], "Unpatched")
        self.assertEqual(alt["CVE-2026-2002"], ("Ignored", "not-applicable-config"))

    @unittest.skipUnless(scanner(), "set SBOM_CVE_CHECK to sbom-cve-check 1.4.0 to scan")
    def test_a_recipe_that_lists_only_fetched_files_gets_unpatched(self):
        # Every recipe's build reaches the feed document here. busybox's lists
        # only the configuration it fetched, which the scanner reads as its
        # compiled sources, so a CVE in a source file reads as not compiled.
        self.run_feed_sbom(mc_recipes=self.kernel_trees(
            busybox_cpe="cpe:2.3:a:busybox:busybox:1.36.1:*:*:*:*:*:*:*",
            busybox_sources=("defconfig",)))
        record = ("CVE-2026-2101", ["networking/httpd.c"], "busybox", "1.37.0")
        scanned = self.scan([record])
        self.assertEqual(scanned[("busybox", "1.36.1")]["CVE-2026-2101"],
                         ("Ignored", "not-applicable-config"))
        doc, _stats = report.build_report(
            [str(self.scan_path)], [str(self.tmp / "pkgdata" / "raspberrypi5")],
            status=report.STATUS_ALL, compiled_sources={"linux-raspberrypi"})
        busybox = {c["id"]: c for c in doc["recipes"]["busybox"]["cves"]}
        self.assertEqual(busybox["CVE-2026-2101"]["status"], "Unpatched")
        self.assertNotIn("detail", busybox["CVE-2026-2101"])
        self.assertEqual(busybox["CVE-2026-2101"]["scanner"]["detail"], "not-applicable-config")
        kernel = {c["id"]: c for c in doc["recipes"]["linux-raspberrypi"]["cves"]}
        self.assertEqual((kernel["CVE-2026-2001"]["status"], kernel["CVE-2026-2001"]["detail"]),
                         ("Ignored", "not-applicable-config"))

    def test_constants_match_oe_sbom30(self):
        sbom30 = self.oe.sbom30
        self.assertEqual(spdxalias.ALIAS_PREFIX, sbom30.OE_ALIAS_PREFIX)
        self.assertEqual(spdxalias.DOC_ALIAS_PREFIX, sbom30.OE_DOC_ALIAS_PREFIX)
        self.assertEqual(spdxalias.ALIAS_TYPE, sbom30.OE_SPDX_BASE + "id-alias")
        d = self.datastore(self.tmp, "linux-raspberrypi", "2" * 64)
        objset = sbom30.ObjectSet.new_objset(d, "recipe-linux-raspberrypi", False)
        alias = sbom30.get_alias(objset.doc).alias
        self.assertEqual(spdxalias.element_prefix(alias),
                         sbom30.OE_ALIAS_PREFIX + sbom30.hash_id(alias) + "/")
        self.assertEqual(spdxalias.element_prefix(alias), objset.alias_prefix)

    def test_document_alias_reads_a_written_document(self):
        self.build_trees(alt=False)
        path = (self.tmp / "deploy" / "spdx" / "raspberrypi5" / "recipes"
                / "recipe-linux-raspberrypi.spdx.json")
        data = json.loads(path.read_text())
        objset = self.oe.sbom30.load_jsonld(self.datastore(self.tmp, "x", "0" * 64), path)
        self.assertEqual(spdxalias.document_alias(data),
                         self.oe.sbom30.get_alias(objset.doc).alias)


if __name__ == "__main__":
    unittest.main()
