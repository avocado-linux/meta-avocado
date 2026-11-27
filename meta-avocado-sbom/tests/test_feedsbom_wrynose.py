#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""Feed scope on wrynose: the kernel CVE filter, alternate kernels' VEX
statements and alternate kernels' unresolved links.

RealLibTest writes a default tree and alternate multiconfig trees with wrynose
OE-core's own oe.sbom30, laid out as create-spdx-3.0 writes them (static/,
builds/, packages-staging/, packages/), runs the recipe's do_feed_sbom on them and reads
the document it writes. It runs when OE_CORE_LIB names wrynose OE-core's
meta/lib. ScanTest also runs the pinned sbom-cve-check on that document against
a small cvelist database; it runs when SBOM_CVE_CHECK names the tool too.

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

from avocado_sbom import feedcheck, feedsbom, spdxalias  # noqa: E402

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


class Fatal(Exception):
    pass


class D:
    """The slice of a bitbake datastore the feed task and oe.sbom30 read.

    NAME:<override> values apply when <override> is in OVERRIDES, the last one
    listed winning, as bitbake resolves pn-<recipe> settings from local.conf.
    """

    def __init__(self, values):
        self.values = dict(values)

    def getVar(self, name, expand=True):
        value = self.values.get(name)
        for override in (self.values.get("OVERRIDES") or "").split(":"):
            if override and name + ":" + override in self.values:
                value = self.values[name + ":" + override]
        return value

    def setVar(self, name, value):
        self.values[name] = value

    def getVarFlag(self, name, flag):
        return None

    def expand(self, s):
        return s


MACHINE = "avocado-jetson-orin-nano"
ARCH = "jetson_orin_nano"
ARCHS = "allarch armv8a %s x86_64" % ARCH
FEED_NAME = "avocado-feed-jetson-orin-nano"
KERNEL_CPE = "cpe:2.3:o:linux:linux_kernel:%s:*:*:*:*:*:*:*"

EDK2_CPE = "cpe:2.3:a:tianocore:edk2:202505:*:*:*:*:*:*:*"
OOT_CPE = "cpe:2.3:a:nvidia:jetson_linux:39.2.1:*:*:*:*:*:*:*"
TEGRA_MCS = (("jetson-l4t", "8"), ("jetson-rt", "9"), ("jetson-l4t-rt", "a"))

# The kernel's compiled sources: what create_spdx keeps of the source walk
# under SPDX_INCLUDE_COMPILED_SOURCES. init/main.c passes the scanner's check
# that a kernel's list is real.
COMPILED = ("init/main.c", "kernel/fork.c", "drivers/net/compiled.c")


def load_oe(test, lib):
    """Put a stand-in bb and wrynose OE-core's spdx30, spdx_common and sbom30 in
    sys.modules for the duration of test."""
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
    before = set(sys.modules)
    saved = {k: sys.modules.get(k) for k in mods}
    sys.modules.update(mods)

    def restore():
        for k in set(sys.modules) - before:
            if k.startswith("oe.") or k == "oe":
                sys.modules.pop(k, None)
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
    test.addCleanup(restore)

    package = lib / "oe" / "spdx30"
    spec = importlib.util.spec_from_file_location(
        "oe.spdx30", package / "__init__.py", submodule_search_locations=[str(package)])
    mod = importlib.util.module_from_spec(spec)
    sys.modules["oe.spdx30"] = mod
    oe.spdx30 = mod
    spec.loader.exec_module(mod)
    for name in ("spdx_common", "sbom30"):
        spec = importlib.util.spec_from_file_location("oe." + name, lib / "oe" / (name + ".py"))
        mod = importlib.util.module_from_spec(spec)
        sys.modules["oe." + name] = mod
        setattr(oe, name, mod)
        spec.loader.exec_module(mod)
    return bb, oe


def wrynose_lib():
    lib = os.environ.get("OE_CORE_LIB")
    if not lib:
        return None
    lib = Path(lib)
    # scarthgap's oe/spdx30.py is a module; wrynose's is a package with static
    # recipe documents.
    if not (lib / "oe" / "spdx30" / "__init__.py").is_file():
        return None
    return lib


class Trees:
    """Writes the trees and runs the task; the test classes below use it."""

    def setUp(self):
        self.bb, self.oe = load_oe(self, wrynose_lib())
        self.top = Path(tempfile.mkdtemp(prefix="feed-wrynose-"))
        self.addCleanup(shutil.rmtree, self.top)
        self.tmp = self.top / "tmp"
        self.base = {
            "SPDX_UUID_NAMESPACE": "sbom.openembedded.org",
            "SPDX_NAMESPACE_PREFIX": "http://spdx.org/spdxdocs",
            "SPDX_TOOL_NAME": "oe-spdx-creator", "SPDX_TOOL_VERSION": "1.0",
            "SPDX_AUTHORS": "openembedded",
            "SPDX_AUTHORS_openembedded_name": "OpenEmbedded",
            "SPDX_AUTHORS_openembedded_type": "organization",
            "SPDX_VERSION": "3.0.1", "SOURCE_DATE_EPOCH": "0",
            "SPDX_PROFILES": "core build software simpleLicensing security",
            "SPDX_MULTILIB_SSTATE_ARCHS": ARCHS,
        }
        self.trees = set()

    # --- writing trees the way create-spdx-3.0 does -------------------------

    def tmp_of(self, mc):
        return self.tmp if not mc else self.top / ("tmp-" + mc)

    def datastore(self, mc, pn, unihash, task, arch=ARCH):
        return D(dict(self.base, PN=pn, BB_UNIHASH=unihash, SSTATE_PKGARCH=arch,
                      BB_CURRENTTASK=task,
                      DEPLOY_DIR_SPDX=str(self.tmp_of(mc) / "deploy" / "spdx")))

    def ensure_tree(self, mc):
        if mc in self.trees:
            return
        self.trees.add(mc)
        sbom30 = self.oe.sbom30
        d = self.datastore(mc, "bitbake", "b" * 64, "create_spdx")
        objset = sbom30.ObjectSet.new_objset(d, "bitbake", False)
        sbom30.write_jsonld_doc(d, objset, self.tmp_of(mc) / "deploy" / "spdx" / "bitbake.spdx.json")

    def write_recipe(self, pn, version, unihash, packages=(), mc="", vex=(), deps=(),
                     sources=None, cpe=None, arch=ARCH, pkgdata=True, build_deps=()):
        """static/static-<pn>, builds/build-<pn> and one packages-staging and
        one packages document per package, as wrynose's create_recipe_spdx,
        create_spdx and create_package_spdx write them. vex holds (CVE, status, detail) with status Patched or
        Ignored; deps name recipes whose recipe and build documents this one
        depends on, build_deps those only its build document depends on;
        sources are the build's compiled source files."""
        self.ensure_tree(mc)
        sbom30, spdx30 = self.oe.sbom30, self.oe.spdx30
        deploy = self.tmp_of(mc) / "deploy" / "spdx"
        pv = version + "+git"
        cpes = [cpe or "cpe:2.3:a:%s:%s:%s:*:*:*:*:*:*:*" % (pn, pn, version)]

        d = self.datastore(mc, pn, unihash, "create_recipe_spdx", arch)
        static = sbom30.ObjectSet.new_objset(d, "static-" + pn)
        recipe = static.add_root(spdx30.software_Package(
            _id=static.new_spdxid("recipe", pn), creationInfo=static.doc.creationInfo,
            name=pn, software_packageVersion=pv,
            software_primaryPurpose=spdx30.software_SoftwarePurpose.specification))
        for c in cpes:
            recipe.externalIdentifier.append(spdx30.ExternalIdentifier(
                externalIdentifierType=spdx30.ExternalIdentifierType.cpe23, identifier=c))
        deps = [dep if isinstance(dep, tuple) else (mc, dep) for dep in deps]
        if deps:
            static.new_scoped_relationship(
                [recipe], spdx30.RelationshipType.dependsOn, spdx30.LifecycleScopeType.build,
                sorted(self.link(dep_mc, dep, "recipe") for dep_mc, dep in deps))
        vulns = []
        for cve, status, detail, *patch in vex:
            v = static.new_cve_vuln(cve)
            vulns.append(v)
            vid = sbom30.get_element_link_id(v)
            if status == "Patched":
                rels = static.new_vex_patched_relationship([vid], [recipe], notes=detail)
                for name in patch:
                    path = self.top / "patches" / (mc or "default") / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(name)
                    static.new_scoped_relationship(
                        rels, spdx30.RelationshipType.patchedBy, spdx30.LifecycleScopeType.build,
                        [static.new_file(static.new_spdxid("patch", "0", name), name, path,
                                         purposes=[spdx30.software_SoftwarePurpose.patch])])
            else:
                static.new_vex_ignored_relationship([vid], [recipe], impact_statement="not affected",
                                                    notes=detail)
        if vulns:
            static.new_relationship([recipe], spdx30.RelationshipType.hasAssociatedVulnerability,
                                    sorted(vulns, key=lambda v: v._id))
        sbom30.write_recipe_jsonld_doc(d, static, "static", deploy)

        d = self.datastore(mc, pn, unihash, "create_spdx", arch)
        builds = sbom30.ObjectSet.new_objset(d, "build-" + pn)
        build = builds.new_task_build("recipe", "recipe")
        builds.set_element_alias(build)
        builds.doc.rootElement.append(build)
        build_deps = deps + [dep if isinstance(dep, tuple) else (mc, dep) for dep in build_deps]
        if build_deps:
            builds.new_scoped_relationship(
                [build], spdx30.RelationshipType.dependsOn, spdx30.LifecycleScopeType.build,
                sorted(self.link(dep_mc, dep, "build") for dep_mc, dep in build_deps))
        if sources:
            workdir = self.top / "work" / (mc or "default") / pn
            files = []
            for i, name in enumerate(sources, 1):
                path = workdir / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("%s %s %s\n" % (mc, pn, name))
                files.append(builds.new_file(builds.new_spdxid("sourcefile", str(i)), name, path,
                                             purposes=[spdx30.software_SoftwarePurpose.source]))
            builds.new_scoped_relationship(
                [build], spdx30.RelationshipType.hasInput, spdx30.LifecycleScopeType.build,
                sorted(files, key=lambda f: f._id))
        staged = []
        for name in packages:
            pkgs = sbom30.ObjectSet.new_objset(d, "package-" + name)
            pkg = pkgs.add_root(spdx30.software_Package(
                _id=pkgs.new_spdxid("package", name), creationInfo=pkgs.doc.creationInfo,
                name=name, software_packageVersion=pv,
                software_primaryPurpose=spdx30.software_SoftwarePurpose.install))
            pkgs.new_scoped_relationship(
                [sbom30.get_element_link_id(build)], spdx30.RelationshipType.hasOutput,
                spdx30.LifecycleScopeType.build, [pkg])
            pkgs.new_scoped_relationship(
                [sbom30.get_element_link_id(recipe)], spdx30.RelationshipType.generates,
                spdx30.LifecycleScopeType.build, [pkg])
            for c in cpes:
                pkg.externalIdentifier.append(spdx30.ExternalIdentifier(
                    externalIdentifierType=spdx30.ExternalIdentifierType.cpe23, identifier=c))
            sbom30.write_recipe_jsonld_doc(d, pkgs, "packages-staging", deploy,
                                           create_spdx_id_links=False)
            staged.append((name, pkgs, pkg))
        # packages/, as do_create_package_spdx writes it: the staged document
        # plus a runtime dependency on the recipe's first package.
        for name, pkgs, pkg in staged:
            if staged and name != staged[0][0]:
                pkgs.new_scoped_relationship(
                    [pkg], spdx30.RelationshipType.dependsOn, spdx30.LifecycleScopeType.runtime,
                    [sbom30.get_element_link_id(staged[0][2])])
            sbom30.write_recipe_jsonld_doc(d, pkgs, "packages", deploy)
        sbom30.write_recipe_jsonld_doc(d, builds, "builds", deploy)
        if pkgdata and packages:
            reverse = self.tmp_of(mc) / "pkgdata" / ARCH / "runtime-reverse"
            reverse.mkdir(parents=True, exist_ok=True)
            for name in packages:
                (reverse / name).write_text("PN: %s\nPV: %s\nPKGV: %s\nPKGR: r0\n"
                                            % (pn, pv, pv))

    def link(self, mc, pn, kind):
        """The alias a document of pn in mc's tree gives its recipe package or
        its build, as another recipe's document links to it."""
        subdir, name = {"recipe": ("static", "static-"), "build": ("builds", "build-")}[kind]
        for arch in ARCHS.split():
            path = self.tmp_of(mc) / "deploy" / "spdx" / arch / subdir / (name + pn + ".spdx.json")
            if path.exists():
                data = json.loads(path.read_text())
                for node in data["@graph"]:
                    want = "software_Package" if kind == "recipe" else "build_Build"
                    if node.get("type") == want:
                        for ext in node.get("extension", []):
                            alias = ext.get("https://rdf.openembedded.org/spdx/3.0/alias")
                            if alias:
                                return alias
        raise AssertionError("no %s document of %s in %r" % (kind, pn, mc))

    # --- the trees ----------------------------------------------------------

    def jetson(self, rt_vex=(), rt_deps=(), default_vex=(), rt_version="6.18.52",
               rt_build_deps=()):
        """A default stock kernel, an RT kernel of the same product and version
        in jetson-rt, and busybox. Both kernels' builds list compiled sources;
        run_feed_sbom's compiled names the recipes the setting covers, the stock
        kernel only by default, as on Jetson. Both kernels depend on a native recipe, whose documents carry
        the same aliases in every tree; the RT kernel's link to it resolves in
        the default tree."""
        self.write_recipe("bc-native", "1.08.2", "1" * 64, arch="x86_64")
        self.write_recipe("linux-yocto", "6.18.52", "2" * 64,
                          ["kernel", "kernel-image-6.18.52"], vex=default_vex,
                          deps=["bc-native"], sources=COMPILED, cpe=KERNEL_CPE % "6.18.52")
        self.write_recipe("busybox", "1.37.0", "3" * 64, ["busybox", "busybox-syslog"],
                          vex=[("CVE-2025-0003", "Ignored", "cpe-incorrect")])
        self.write_recipe("linux-yocto-rt", rt_version, "4" * 64,
                          ["kernel", "kernel-image-%s-rt" % rt_version], mc="jetson-rt",
                          vex=rt_vex, deps=[("", "bc-native")] + list(rt_deps),
                          build_deps=rt_build_deps, sources=COMPILED,
                          cpe=KERNEL_CPE % rt_version)

    def tegra(self, alt_vex=None, run=True, alt_cpe=OOT_CPE):
        """Jetson's nvidia-kernel-oot (CPE product jetson_linux) beside
        edk2-firmware-tegra (edk2), both at recipe version 39.2.1, the firmware
        with a statement about an edk2 CVE; nvidia-kernel-oot again in each of
        three alternate multiconfigs, with alt_vex[mc] as its statements."""
        alt_vex = alt_vex or {}
        self.write_recipe("edk2-firmware-tegra", "39.2.1", "6" * 64, ["edk2-firmware-tegra"],
                          vex=[("CVE-2026-2001", "Patched", "fixed-version")], cpe=EDK2_CPE)
        self.write_recipe("nvidia-kernel-oot", "39.2.1", "7" * 64,
                          ["nvidia-kernel-oot-base", "nv-kernel-module-x-6.18.52"], cpe=OOT_CPE)
        for mc, h in TEGRA_MCS:
            self.write_recipe("nvidia-kernel-oot", "39.2.1", h * 64,
                              ["nvidia-kernel-oot-base", "nv-kernel-module-x-%s" % mc],
                              mc=mc, vex=alt_vex.get(mc, ()), cpe=alt_cpe)
        if run:
            return self.run_feed_sbom(
                mc_recipes=" ".join("%s:nvidia-kernel-oot" % mc for mc, _h in TEGRA_MCS),
                compiled=())

    def run_feed_sbom(self, mc_recipes="jetson-rt:linux-yocto-rt", compiled=("linux-yocto",)):
        deploy = self.tmp / "deploy"
        feed_dir = deploy / "avocado-cve"
        values = dict(
            self.base, PN="avocado-cve-report", BB_UNIHASH="5" * 64,
            SSTATE_PKGARCH=ARCH, MACHINE=MACHINE, OVERRIDES="pn-avocado-cve-report",
            TOPDIR=str(self.top), TMPDIR=str(self.tmp),
            DEPLOY_DIR_SPDX=str(deploy / "spdx"),
            PKGDATA_DIR=str(self.tmp / "pkgdata" / ARCH),
            AVOCADO_FEED_SBOM_DIR=str(feed_dir), AVOCADO_FEED_SBOM_NAME=FEED_NAME,
            AVOCADO_FEED_SBOM_FILE=str(feed_dir / (FEED_NAME + ".spdx.json")),
            AVOCADO_FEED_COVERAGE_FILE=str(feed_dir / (FEED_NAME + ".coverage.json")),
            AVOCADO_CVE_REPORT_FILE=str(feed_dir / ("avocado-cve-report-%s.json" % MACHINE)),
            AVOCADO_RPM_MANIFEST_FILE=str(feed_dir / ("avocado-rpm-manifest-%s.json" % MACHINE)),
            AVOCADO_FEED_SBOM_MAX_MISSING="33",
            AVOCADO_MULTIKERNEL_MC_RECIPES=mc_recipes,
            SPDX_INCLUDE_COMPILED_SOURCES="0",
        )
        for pn in compiled:
            values["SPDX_INCLUDE_COMPILED_SOURCES:pn-" + pn] = "1"
        d = D(values)
        ns = {"bb": self.bb, "os": os, "d": d}
        exec(recipe_functions(), ns)
        exec("def do_feed_sbom(d):\n" + textwrap.indent(recipe_python("do_feed_sbom"), "    "), ns)
        ns["do_feed_sbom"](d)
        self.document_path = Path(d.getVar("AVOCADO_FEED_SBOM_FILE"))
        with open(d.getVar("AVOCADO_FEED_SBOM_FILE")) as f:
            document = json.load(f)
        with open(d.getVar("AVOCADO_FEED_COVERAGE_FILE")) as f:
            coverage = json.load(f)
        return document, coverage

    # --- reading the document the way the scanner does ----------------------

    @staticmethod
    def graph(document):
        return {n["spdxId"]: n for n in document["@graph"] if "spdxId" in n}

    def scanner_view(self, document):
        """{recipe package name: (build name or None, sorted compiled source
        names)}, grouped as sbom-cve-check 1.4.0 groups an install package with
        its build (hasOutput, scope build) and recipe package (generates)."""
        nodes = self.graph(document)

        def scoped(n, typ):
            return (n.get("type") == "LifecycleScopedRelationship"
                    and n.get("relationshipType") == typ and n.get("scope") == "build")
        view = {}
        for n in nodes.values():
            if not scoped(n, "generates"):
                continue
            spec = nodes[n["from"]]
            for pkg_id in n["to"]:
                builds = [nodes[r["from"]] for r in nodes.values()
                          if scoped(r, "hasOutput") and pkg_id in r["to"]
                          and nodes[r["from"]].get("type") == "build_Build"]
                for build in builds:
                    sources = sorted(
                        nodes[t]["name"] for r in nodes.values()
                        if r.get("type") == "LifecycleScopedRelationship"
                        and r.get("relationshipType") == "hasInput" and r["from"] == build["spdxId"]
                        for t in r["to"]
                        if nodes.get(t, {}).get("type") == "software_File"
                        and nodes[t].get("software_primaryPurpose") == "source")
                    view.setdefault(spec["name"], set()).add((build["name"], tuple(sources)))
        return view

    def specs(self, document):
        return sorted((n["name"], n["software_packageVersion"])
                      for n in self.graph(document).values()
                      if n.get("type") == "software_Package"
                      and n.get("software_primaryPurpose") == "specification")



@unittest.skipUnless(wrynose_lib(), "set OE_CORE_LIB to wrynose OE-core's meta/lib to run against it")
class RealLibTest(Trees, unittest.TestCase):
    # --- F1: the kernel CVE filter -------------------------------------------
    def test_alias_constants_match_oe_sbom30(self):
        sbom30 = self.oe.sbom30
        self.assertEqual(spdxalias.ALIAS_PREFIX, sbom30.OE_ALIAS_PREFIX)
        self.assertEqual(spdxalias.DOC_ALIAS_PREFIX, sbom30.OE_DOC_ALIAS_PREFIX)
        self.assertEqual(spdxalias.ALIAS_TYPE, sbom30.OE_SPDX_BASE + "id-alias")
        self.ensure_tree("")
        d = self.datastore("", "linux-yocto", "2" * 64, "create_spdx")
        objset = sbom30.ObjectSet.new_objset(d, "build-linux-yocto")
        alias = sbom30.get_alias(objset.doc).alias
        self.assertEqual(spdxalias.element_prefix(alias), objset.alias_prefix)


    def test_a_compiled_source_kernel_brings_its_build(self):
        self.jetson()
        document, coverage = self.run_feed_sbom(mc_recipes="")
        view = self.scanner_view(document)
        self.assertEqual(view, {"linux-yocto": {(
            "linux-yocto:do_create_spdx:recipe", tuple(sorted(COMPILED)))}})
        self.assertEqual(coverage["roots"], 2)
        sbom, = [n for n in document["@graph"] if n.get("type") == "software_Sbom"]
        nodes = self.graph(document)
        self.assertEqual(sorted(nodes[r]["name"] for r in sbom["rootElement"]),
                         ["busybox", "linux-yocto"])

    def test_other_recipes_bring_no_build_or_package(self):
        self.jetson()
        document, _coverage = self.run_feed_sbom(mc_recipes="")
        nodes = self.graph(document)
        installs = sorted(n["name"] for n in nodes.values()
                          if n.get("type") == "software_Package"
                          and n.get("software_primaryPurpose") == "install")
        self.assertEqual(installs, ["kernel", "kernel-image-6.18.52"])
        builds = sorted(n["name"] for n in nodes.values() if n.get("type") == "build_Build")
        # The kernel's build pulls in the builds it depends on, which describe
        # no package the scanner reads.
        self.assertEqual(builds, ["bc-native:do_create_spdx:recipe",
                                  "linux-yocto:do_create_spdx:recipe"])

    def test_without_the_setting_the_kernel_has_no_build(self):
        self.jetson()
        document, _coverage = self.run_feed_sbom(mc_recipes="", compiled=())
        self.assertEqual(self.scanner_view(document), {})
        self.assertNotIn("build_Build", {n.get("type") for n in document["@graph"]})

    def test_feedcheck_accepts_the_document(self):
        self.jetson(rt_vex=[])
        self.run_feed_sbom()
        paths = feedcheck.Paths(str(self.tmp), MACHINE)
        for check in (feedcheck.check_document_exists, feedcheck.check_document_jsonld,
                      feedcheck.check_document_roots, feedcheck.check_coverage_record):
            name, ok, detail = check(paths)
            self.assertTrue(ok, "%s: %s" % (name, detail))

    def test_an_alternate_kernel_of_the_same_recipe_keeps_its_own_build(self):
        # Raspberry Pi: one recipe, two versions, both listing compiled
        # sources. Both kernels' documents carry the same aliases.
        self.write_recipe("linux-raspberrypi", "6.12.47", "2" * 64, ["kernel", "kernel-image"],
                          sources=COMPILED, cpe=KERNEL_CPE % "6.12.47")
        self.write_recipe("linux-raspberrypi", "6.6.63", "4" * 64, ["kernel", "kernel-image"],
                          mc="raspberrypi-6_6", sources=("init/main.c", "drivers/only66.c"),
                          cpe=KERNEL_CPE % "6.6.63")
        document, coverage = self.run_feed_sbom(
            mc_recipes="raspberrypi-6_6:linux-raspberrypi", compiled=("linux-raspberrypi",))
        self.assertEqual(coverage["alt_included"], ["raspberrypi-6_6:linux-raspberrypi"])
        self.assertEqual(coverage["alt_not_covered"], [])
        nodes = self.graph(document)
        by_version = {}
        for n in nodes.values():
            if n.get("relationshipType") == "generates":
                spec = nodes[n["from"]]
                for pkg_id in n["to"]:
                    by_version.setdefault(spec["software_packageVersion"], set()).add(
                        nodes[pkg_id]["software_packageVersion"])
        self.assertEqual(by_version, {"6.12.47+git": {"6.12.47+git"},
                                      "6.6.63+git": {"6.6.63+git"}})
        sources = {}
        for n in nodes.values():
            if n.get("relationshipType") != "hasOutput":
                continue
            for pkg_id in n["to"]:
                sources[nodes[pkg_id]["software_packageVersion"]] = sorted(
                    nodes[t]["name"] for r in nodes.values()
                    if r.get("relationshipType") == "hasInput" and r["from"] == n["from"]
                    for t in r["to"])
        self.assertEqual(sources, {"6.12.47+git": sorted(COMPILED),
                                   "6.6.63+git": ["drivers/only66.c", "init/main.c"]})

    # --- F7: an alternate kernel's VEX statements ----------------------------

    def test_an_alternate_with_other_statements_is_left_out(self):
        self.jetson(rt_vex=[("CVE-2026-1003", "Patched", "backported-patch")])
        document, coverage = self.run_feed_sbom()
        self.assertEqual(coverage["alt_included"], [])
        self.assertEqual(coverage["alt_not_covered"], [{
            "mc": "jetson-rt", "recipe": "linux-yocto-rt",
            "reason": "VEX overlap: linux_kernel 6.18.52 is also linux-yocto, with other "
                      "statements on CVE-2026-1003"}])
        self.assertEqual(self.specs(document),
                         [("bc-native", "1.08.2+git"), ("busybox", "1.37.0+git"),
                          ("linux-yocto", "6.18.52+git")])
        self.assertNotIn("CVE-2026-1003", json.dumps(document))

    def test_an_alternate_with_the_same_statements_stays(self):
        same = [("CVE-2025-0001", "Ignored", "cpe-incorrect"),
                ("CVE-2025-0002", "Patched", "fixed-version")]
        self.jetson(rt_vex=same, default_vex=same)
        document, coverage = self.run_feed_sbom()
        self.assertEqual(coverage["alt_included"], ["jetson-rt:linux-yocto-rt"])
        self.assertEqual(coverage["alt_not_covered"], [])
        self.assertIn(("linux-yocto-rt", "6.18.52+git"), self.specs(document))

    def test_a_status_differing_in_detail_only_counts_as_other(self):
        self.jetson(rt_vex=[("CVE-2025-0001", "Ignored", "not-applicable-config")],
                    default_vex=[("CVE-2025-0001", "Ignored", "cpe-incorrect")])
        _document, coverage = self.run_feed_sbom()
        self.assertEqual([e["recipe"] for e in coverage["alt_not_covered"]], ["linux-yocto-rt"])

    def test_the_same_backport_from_another_patch_counts_as_other(self):
        self.jetson(rt_vex=[("CVE-2026-1003", "Patched", "fix-file-included", "rt-fix.patch")],
                    default_vex=[("CVE-2026-1003", "Patched", "fix-file-included", "fix.patch")])
        _document, coverage = self.run_feed_sbom()
        self.assertEqual([e["recipe"] for e in coverage["alt_not_covered"]], ["linux-yocto-rt"])

    def test_an_alternate_left_out_as_unresolved_is_not_compared_with(self):
        # Two L4T-like alternates of one version and other statements; the
        # first links to a tool only its multiconfig built.
        self.jetson(rt_vex=[])
        self.write_recipe("l4t-only-native", "1.0", "a" * 64, mc="jetson-l4t", arch="x86_64")
        for mc, pn, vex, deps in (
                ("jetson-l4t", "linux-l4t", [], [("jetson-l4t", "l4t-only-native")]),
                ("jetson-l4t-rt", "linux-l4t-rt",
                 [("CVE-2026-1003", "Patched", "backported-patch")], [])):
            self.write_recipe(pn, "6.8.12", "b" * 64, ["kernel", "kernel-image-6.8.12"],
                              mc=mc, vex=vex, deps=deps, cpe=KERNEL_CPE % "6.8.12")
        _document, coverage = self.run_feed_sbom(
            mc_recipes="jetson-l4t:linux-l4t jetson-l4t-rt:linux-l4t-rt")
        self.assertEqual(coverage["alt_included"], ["jetson-l4t-rt:linux-l4t-rt"])
        entry, = coverage["alt_not_covered"]
        self.assertTrue(entry["reason"].startswith("unresolved reference: "), entry)

    def test_a_native_dependency_at_the_alternate_version_is_compared_with(self):
        # The native's recipe document comes in through busybox's link, with a
        # statement the scanner would apply to the L4T kernel by version.
        self.write_recipe("tool-native", "6.8.12", "1" * 64, arch="x86_64",
                          vex=[("CVE-2026-4001", "Patched", "fixed-version")])
        self.write_recipe("busybox", "1.37.0", "3" * 64, ["busybox"], deps=["tool-native"])
        self.write_recipe("linux-l4t", "6.8.12", "b" * 64, ["kernel", "kernel-image-6.8.12"],
                          mc="jetson-l4t", cpe=KERNEL_CPE % "6.8.12")
        document, coverage = self.run_feed_sbom(mc_recipes="jetson-l4t:linux-l4t", compiled=())
        self.assertIn(("tool-native", "6.8.12+git"), self.specs(document))
        self.assertEqual(coverage["alt_included"], [])
        self.assertEqual(coverage["alt_not_covered"], [{
            "mc": "jetson-l4t", "recipe": "linux-l4t",
            "reason": "VEX overlap: 6.8.12 is also tool-native, with other statements "
                      "on CVE-2026-4001"}])

    def test_a_statement_of_an_alternate_left_out_this_pass_is_not_compared_with(self):
        # The first alternate goes on an unresolved link and carries a
        # statement the second lacks; its documents are still in this pass's
        # assembly, and must not leave the second out.
        self.jetson(rt_vex=[])
        self.write_recipe("l4t-only-native", "1.0", "a" * 64, mc="jetson-l4t", arch="x86_64")
        for mc, pn, vex, deps in (
                ("jetson-l4t", "linux-l4t", [("CVE-2026-1003", "Patched", "backported-patch")],
                 [("jetson-l4t", "l4t-only-native")]),
                ("jetson-l4t-rt", "linux-l4t-rt", [], [])):
            self.write_recipe(pn, "6.8.12", "b" * 64, ["kernel", "kernel-image-6.8.12"],
                              mc=mc, vex=vex, deps=deps, cpe=KERNEL_CPE % "6.8.12")
        _document, coverage = self.run_feed_sbom(
            mc_recipes="jetson-l4t:linux-l4t jetson-l4t-rt:linux-l4t-rt")
        self.assertEqual(coverage["alt_included"], ["jetson-l4t-rt:linux-l4t-rt"])
        entry, = coverage["alt_not_covered"]
        self.assertTrue(entry["reason"].startswith("unresolved reference: "), entry)

    def test_a_dependency_of_an_alternate_left_out_this_pass_is_not_compared_with(self):
        # Two alternates of one recipe and version. The first goes on an
        # unresolved link and alone links to a native at that version with a
        # statement; the native's documents come in with it, and must not
        # leave the second out.
        self.write_recipe("busybox", "1.37.0", "3" * 64, ["busybox"])
        self.write_recipe("tool-native", "6.8.12", "1" * 64, arch="x86_64",
                          vex=[("CVE-2026-4001", "Patched", "fixed-version")])
        self.write_recipe("l4t-only-native", "1.0", "a" * 64, mc="jetson-l4t", arch="x86_64")
        for mc, h, deps in (("jetson-l4t", "b", [("", "tool-native"),
                                                 ("jetson-l4t", "l4t-only-native")]),
                            ("jetson-l4t-rt", "c", [])):
            self.write_recipe("linux-l4t", "6.8.12", h * 64, ["kernel", "kernel-image-6.8.12"],
                              mc=mc, deps=deps, cpe=KERNEL_CPE % "6.8.12")
        document, coverage = self.run_feed_sbom(
            mc_recipes="jetson-l4t:linux-l4t jetson-l4t-rt:linux-l4t", compiled=())
        self.assertEqual(coverage["alt_included"], ["jetson-l4t-rt:linux-l4t"])
        entry, = coverage["alt_not_covered"]
        self.assertEqual(entry["mc"], "jetson-l4t")
        self.assertTrue(entry["reason"].startswith("unresolved reference: "), entry)
        self.assertNotIn("tool-native", [name for name, _v in self.specs(document)])

    def test_an_alternate_without_its_build_document_is_left_out(self):
        # Its package would otherwise find the default kernel's build under
        # the same alias.
        self.write_recipe("linux-raspberrypi", "6.12.47", "2" * 64, ["kernel"],
                          sources=COMPILED, cpe=KERNEL_CPE % "6.12.47")
        self.write_recipe("linux-raspberrypi", "6.6.63", "4" * 64, ["kernel"],
                          mc="raspberrypi-6_6", sources=COMPILED, cpe=KERNEL_CPE % "6.6.63")
        # A module built for it must not find the default kernel either.
        self.write_recipe("rpi-module", "1.0", "e" * 64, ["kernel-module-x"],
                          mc="raspberrypi-6_6", deps=[("raspberrypi-6_6", "linux-raspberrypi")])
        build, = (self.top / "tmp-raspberrypi-6_6" / "deploy" / "spdx").glob(
            "*/builds/build-linux-raspberrypi.spdx.json")
        build.unlink()
        document, coverage = self.run_feed_sbom(
            mc_recipes="raspberrypi-6_6:linux-raspberrypi raspberrypi-6_6:rpi-module",
            compiled=("linux-raspberrypi",))
        self.assertEqual(coverage["alt_included"], [])
        self.assertEqual(sorted(e["recipe"] for e in coverage["alt_not_covered"]),
                         ["linux-raspberrypi", "rpi-module"])
        self.assertEqual(self.specs(document), [("linux-raspberrypi", "6.12.47+git")])

    def test_another_version_does_not_overlap(self):
        # One stable release on, the scanner cannot match the RT kernel's
        # statements to the stock kernel's version.
        self.jetson(rt_vex=[("CVE-2026-1003", "Patched", "backported-patch")],
                    rt_version="6.18.53")
        _document, coverage = self.run_feed_sbom()
        self.assertEqual(coverage["alt_included"], ["jetson-rt:linux-yocto-rt"])

    # --- Q3: an alternate kernel's links into its own multiconfig ------------

    def test_a_link_only_the_alternate_multiconfig_resolves_leaves_that_kernel_out(self):
        self.write_recipe("rt-only-tool-native", "1.0", "7" * 64, mc="jetson-rt", arch="x86_64")
        self.jetson(rt_deps=[("jetson-rt", "rt-only-tool-native")])
        document, coverage = self.run_feed_sbom()
        self.assertEqual(coverage["alt_included"], [])
        self.assertEqual(len(coverage["alt_not_covered"]), 1)
        entry = coverage["alt_not_covered"][0]
        self.assertEqual((entry["mc"], entry["recipe"]), ("jetson-rt", "linux-yocto-rt"))
        self.assertTrue(entry["reason"].startswith("unresolved reference: "), entry)
        self.assertEqual(coverage["unresolved_ids"], 0)
        self.assertIn(("linux-yocto", "6.18.52+git"), self.specs(document))

    def test_an_unresolved_link_of_the_alternate_build_leaves_that_kernel_out(self):
        # Only the build document links to it, and the build joins the
        # alternate's documents only when that kernel lists compiled sources.
        self.write_recipe("rt-only-tool-native", "1.0", "7" * 64, mc="jetson-rt", arch="x86_64")
        self.jetson(rt_build_deps=[("jetson-rt", "rt-only-tool-native")])
        _document, coverage = self.run_feed_sbom(mc_recipes="jetson-rt:linux-yocto-rt")
        self.assertEqual(coverage["alt_included"], ["jetson-rt:linux-yocto-rt"])
        _document, coverage = self.run_feed_sbom(
            mc_recipes="jetson-rt:linux-yocto-rt", compiled=("linux-yocto", "linux-yocto-rt"))
        self.assertEqual(coverage["alt_included"], [])
        entry, = coverage["alt_not_covered"]
        self.assertTrue(entry["reason"].startswith("unresolved reference: "), entry)

    def test_a_module_of_a_kernel_left_out_is_left_out_too(self):
        # The RT kernel goes on VEX overlap; a module built for it in the same
        # multiconfig then links to a kernel no loaded document defines.
        self.jetson(rt_vex=[("CVE-2026-1003", "Patched", "backported-patch")])
        self.write_recipe("rt-module", "1.0", "c" * 64, ["kernel-module-rt"], mc="jetson-rt",
                          deps=[("jetson-rt", "linux-yocto-rt")])
        document, coverage = self.run_feed_sbom(
            mc_recipes="jetson-rt:linux-yocto-rt jetson-rt:rt-module")
        self.assertEqual(coverage["alt_included"], [])
        reasons = {e["recipe"]: e["reason"].split(":")[0] for e in coverage["alt_not_covered"]}
        self.assertEqual(reasons, {"linux-yocto-rt": "VEX overlap",
                                   "rt-module": "unresolved reference"})
        self.assertEqual(coverage["unresolved_ids"], 0)

    def test_a_module_of_a_kernel_left_out_never_finds_the_default_kernel(self):
        # The 6.6 kernel goes on an unresolved link; its module names it by the
        # same alias as the default kernel, which must not catch the link.
        self.write_recipe("linux-raspberrypi", "6.12.47", "2" * 64, ["kernel"],
                          sources=COMPILED, cpe=KERNEL_CPE % "6.12.47")
        self.write_recipe("rpi66-only-native", "1.0", "d" * 64, mc="raspberrypi-6_6",
                          arch="x86_64")
        self.write_recipe("linux-raspberrypi", "6.6.63", "4" * 64, ["kernel"],
                          mc="raspberrypi-6_6", cpe=KERNEL_CPE % "6.6.63",
                          deps=[("raspberrypi-6_6", "rpi66-only-native")])
        self.write_recipe("rpi-module", "1.0", "e" * 64, ["kernel-module-x"],
                          mc="raspberrypi-6_6", deps=[("raspberrypi-6_6", "linux-raspberrypi")])
        _document, coverage = self.run_feed_sbom(
            mc_recipes="raspberrypi-6_6:linux-raspberrypi raspberrypi-6_6:rpi-module",
            compiled=())
        self.assertEqual(coverage["alt_included"], [])
        self.assertEqual(sorted(e["recipe"] for e in coverage["alt_not_covered"]),
                         ["linux-raspberrypi", "rpi-module"])

    def test_a_module_of_a_kernel_without_its_document_never_finds_the_default_kernel(self):
        # The 6.6 kernel's recipe document is missing; its module names it by
        # the alias the default kernel's document carries.
        self.write_recipe("linux-raspberrypi", "6.12.47", "2" * 64, ["kernel"],
                          sources=COMPILED, cpe=KERNEL_CPE % "6.12.47")
        self.write_recipe("linux-raspberrypi", "6.6.63", "4" * 64, ["kernel"],
                          mc="raspberrypi-6_6", cpe=KERNEL_CPE % "6.6.63")
        self.write_recipe("rpi-module", "1.0", "e" * 64, ["kernel-module-x"],
                          mc="raspberrypi-6_6", deps=[("raspberrypi-6_6", "linux-raspberrypi")])
        static, = (self.top / "tmp-raspberrypi-6_6" / "deploy" / "spdx").glob(
            "*/static/static-linux-raspberrypi.spdx.json")
        static.unlink()
        _document, coverage = self.run_feed_sbom(
            mc_recipes="raspberrypi-6_6:linux-raspberrypi raspberrypi-6_6:rpi-module",
            compiled=())
        self.assertEqual(coverage["alt_included"], [])
        reasons = {e["recipe"]: e["reason"].split(":")[0] for e in coverage["alt_not_covered"]}
        self.assertEqual(reasons["rpi-module"], "unresolved reference")
        self.assertIn("linux-raspberrypi", reasons)

    def test_a_hole_in_the_default_tree_still_fails(self):
        # A default recipe whose link resolves in no tree this task reads.
        self.write_recipe("gone-native", "1.0", "8" * 64, mc="other", arch="x86_64")
        self.write_recipe("needs-gone", "1.0", "9" * 64, ["needs-gone"],
                          deps=[("other", "gone-native")])
        with self.assertRaises(Fatal) as cm:
            self.run_feed_sbom(mc_recipes="")
        self.assertIn("refers to 1 identifier(s)", str(cm.exception))
        # Named by the recipe whose document is missing.
        self.assertIn("belong to the documents of gone-native,", str(cm.exception))

    def test_alias_recipe_reads_the_pn_of_an_oe_core_alias(self):
        self.write_recipe("jsoncpp-native", "1.9.6", "1" * 64, arch="x86_64")
        for kind in ("recipe", "build"):
            with self.subTest(kind=kind):
                self.assertEqual(spdxalias.alias_recipe(self.link("", "jsoncpp-native", kind)),
                                 "jsoncpp-native")

    # --- Every SPDX document the feed document links to ---------------------

    def test_the_feed_asks_for_the_spdx_tasks_oe_core_asks_for_an_image(self):
        # OE-Core's sstate restores these only for a task that runs
        # (setscene_depvalid's direct-only tasks); its image SBOM task makes
        # them recursive dependencies. The feed asks for the same set, split:
        # recipe-level documents over the feed targets' graph (do_feed_sbom),
        # builds over the graph of the kernels whose builds it carries
        # (do_feed_builds).
        meta = wrynose_lib().parent
        image = (meta / "classes-recipe" / "create-spdx-image-3.0.bbclass").read_text()
        oe_tasks = re.search(r'^do_create_image_sbom_spdx\[recrdeptask\] \+= "([^"]*)"',
                             image, re.M).group(1).split()
        text = RECIPE.read_text()
        recipe_level = re.search(r'appendVarFlag\("do_feed_sbom", "recrdeptask",\s*" ([^"]*)"\)',
                                 text).group(1).split()
        builds = re.findall(r'"(do_\w+)"', re.search(r"build_tasks = \(([^)]*)\)", text).group(1))
        self.assertEqual(recipe_level, ["do_create_recipe_spdx"])
        self.assertEqual(sorted(recipe_level + builds), sorted(oe_tasks))
        sstate = (meta / "classes-global" / "sstate.bbclass").read_text()
        direct = re.search(r"directtasks = \[(.*?)\]", sstate).group(1)
        for task in ("do_create_recipe_spdx", "do_create_spdx"):
            self.assertIn('"%s"' % task, direct)

    # --- A module recipe beside firmware of its version (Jetson) -------------

    def test_every_alternate_module_recipe_stays_beside_firmware_of_its_version(self):
        _document, coverage = self.tegra()
        self.assertEqual(coverage["alt_included"], [
            "jetson-l4t:nvidia-kernel-oot", "jetson-rt:nvidia-kernel-oot",
            "jetson-l4t-rt:nvidia-kernel-oot"])
        self.assertEqual(coverage["alt_not_covered"], [])

    def test_another_cpe_vendor_is_no_twin(self):
        # One product name, but a vendor wildcard the scanner matches more
        # widely with: judged on its own, it shares a version with the firmware.
        _document, coverage = self.tegra(
            alt_cpe="cpe:2.3:a:*:jetson_linux:39.2.1:*:*:*:*:*:*:*")
        self.assertEqual(coverage["alt_included"], [])
        self.assertEqual({e["reason"] for e in coverage["alt_not_covered"]}, {
            "VEX overlap: 39.2.1+git is also edk2-firmware-tegra, with other "
            "statements on CVE-2026-2001"})

    def test_a_statement_about_the_firmware_cve_on_the_module_recipe_is_an_overlap(self):
        # Both now carry a statement about CVE-2026-2001, each naming its own
        # product, so the scanner matches the CVE to both.
        _document, coverage = self.tegra(
            alt_vex={"jetson-rt": [("CVE-2026-2001", "Ignored", "cpe-incorrect")]})
        self.assertEqual(coverage["alt_included"], [
            "jetson-l4t:nvidia-kernel-oot", "jetson-l4t-rt:nvidia-kernel-oot"])
        self.assertEqual(coverage["alt_not_covered"], [{
            "mc": "jetson-rt", "recipe": "nvidia-kernel-oot",
            "reason": "VEX overlap: 39.2.1+git is also edk2-firmware-tegra, with other "
                      "statements on CVE-2026-2001"}])


def scanner():
    tool = os.environ.get("SBOM_CVE_CHECK")
    return tool if tool and os.access(tool, os.X_OK) else None


def cve_record(cve, program_files=(), less_than="6.18.99",
               cpe="cpe:2.3:o:linux:linux_kernel:*:*:*:*:*:*:*:*", also=()):
    """A cvelistV5 record: cpe's product (linux_kernel) below less_than
    affected, its fix in program_files; also holds further (cpe, less_than)."""
    record = _cve_record(cve, program_files, less_than, cpe)
    for other_cpe, other_less_than in also:
        record["containers"]["cna"]["affected"] += _cve_record(
            cve, (), other_less_than, other_cpe)["containers"]["cna"]["affected"]
    return record


def _cve_record(cve, program_files, less_than, cpe):
    affected = {
        "vendor": cpe.split(":")[3], "product": cpe.split(":")[4],
        "cpes": [cpe],
        "defaultStatus": "unaffected",
        "versions": [{"version": "0", "lessThan": less_than, "status": "affected",
                      "versionType": "semver"}],
    }
    if program_files:
        affected["programFiles"] = list(program_files)
    return {
        "dataType": "CVE_RECORD", "dataVersion": "5.1",
        "cveMetadata": {"cveId": cve, "state": "PUBLISHED",
                        "datePublished": "2026-01-01T00:00:00.000Z",
                        "dateUpdated": "2026-01-01T00:00:00.000Z"},
        "containers": {"cna": {
            "providerMetadata": {"orgId": "00000000-0000-0000-0000-000000000000",
                                 "dateUpdated": "2026-01-01T00:00:00.000Z"},
            "descriptions": [{"lang": "en", "value": "test record %s" % cve}],
            "affected": [affected],
        }},
    }


@unittest.skipUnless(wrynose_lib() and scanner(),
                     "set OE_CORE_LIB (wrynose meta/lib) and SBOM_CVE_CHECK (sbom-cve-check 1.4.0)")
class ScanTest(Trees, unittest.TestCase):
    """The feed document scanned by sbom-cve-check against three kernel CVEs:
    1001 fixed in a file the stock kernel does not compile, 1002 in one it
    does, 1003 backported in the RT kernel only."""

    RECORDS = (("CVE-2026-1001", ["drivers/bar/notcompiled.c"]),
               ("CVE-2026-1002", ["kernel/fork.c"]),
               ("CVE-2026-1003", []))

    def scan(self, records=None, by_version=False, entries=False):
        db = self.top / "cvelist"
        for cve, files, *extra in records or self.RECORDS:
            year, number = cve.split("-")[1:]
            path = db / "cves" / year / (number[:-3] + "xxx") / (cve + ".json")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(cve_record(cve, files, **(extra[0] if extra else {}))))
        git = ["git", "-C", str(db), "-c", "user.name=t", "-c", "user.email=t@t",
               "-c", "commit.gpgsign=false"]
        subprocess.run(git[:3] + ["init", "-q"], check=True)
        subprocess.run(git + ["add", "-A"], check=True)
        subprocess.run(git + ["commit", "-q", "-m", "records"], check=True)
        out = self.top / "scan.yocto.json"
        subprocess.run(
            [scanner(), "--sbom-path", str(self.document_path), "--disable-auto-updates",
             "--ignore-default-config", "--offline-mode",
             "--no-builtin-products-db", "--export-process-native",
             "--add-db", "cve-db-cvelist", str(db), "offline_mode=true",
             "--export-type", "yocto-cve-check-manifest", "--export-path", str(out)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            env=dict(os.environ, SBOM_CVE_CHECK_DATABASES_DIR=str(self.top / "dbs")))
        result = {}
        listed = []
        for entry in json.loads(out.read_text())["package"]:
            issues = {i["id"]: (i["status"], i.get("detail")) for i in entry["issue"]}
            listed.append((entry["name"], entry["version"], issues))
            key = (entry["name"], entry["version"]) if by_version else entry["name"]
            result[key] = issues
        return listed if entries else result

    # Raspberry Pi: one recipe at two versions, both listing compiled sources,
    # and two CVEs, each fixed in a file only one of the two compiles.
    RPI_RECORDS = (("CVE-2026-1101", ["drivers/only66.c"]),
                   ("CVE-2026-1102", ["drivers/net/compiled.c"]))
    RPI_EXPECTED = {
        ("linux-raspberrypi", "6.12.47+git"): {
            "CVE-2026-1101": ("Ignored", "not-applicable-config"),
            "CVE-2026-1102": ("Unpatched", "version-in-range")},
        ("linux-raspberrypi", "6.6.63+git"): {
            "CVE-2026-1101": ("Unpatched", "version-in-range"),
            "CVE-2026-1102": ("Ignored", "not-applicable-config")},
    }

    def raspberrypi(self):
        self.write_recipe("linux-raspberrypi", "6.12.47", "2" * 64,
                          ["kernel", "kernel-image-6.12.47"],
                          sources=COMPILED, cpe=KERNEL_CPE % "6.12.47")
        self.write_recipe("linux-raspberrypi", "6.6.63", "4" * 64,
                          ["kernel", "kernel-image-6.6.63"], mc="raspberrypi-6_6",
                          sources=("init/main.c", "drivers/only66.c"),
                          cpe=KERNEL_CPE % "6.6.63")
        return self.run_feed_sbom(mc_recipes="raspberrypi-6_6:linux-raspberrypi",
                                  compiled=("linux-raspberrypi",))

    def test_with_the_aliases_left_alone_one_kernel_hides_the_other(self):
        # What the qualified aliases prevent: the two kernels' packages, builds
        # and recipes link to each other by the same aliases, and which ones
        # win depends on load order. The scanner then reports one kernel at
        # one version, or the 6.6 kernel without its filter; never both right.
        real = spdxalias.remap
        spdxalias.remap = lambda value, mapping: value
        self.addCleanup(setattr, spdxalias, "remap", real)
        self.raspberrypi()
        result = self.scan(self.RPI_RECORDS, by_version=True)
        self.assertNotEqual(result, self.RPI_EXPECTED)

    def test_both_raspberry_pi_kernels_are_filtered_each_at_its_own_version(self):
        _document, coverage = self.raspberrypi()
        self.assertEqual(coverage["alt_included"], ["raspberrypi-6_6:linux-raspberrypi"])
        result = self.scan(self.RPI_RECORDS, by_version=True)
        self.assertEqual(result, self.RPI_EXPECTED)

    def test_the_filter_applies_to_the_stock_kernel(self):
        self.jetson(rt_vex=[])
        self.run_feed_sbom()
        result = self.scan()
        self.assertEqual(result["linux-yocto"]["CVE-2026-1001"],
                         ("Ignored", "not-applicable-config"))
        self.assertEqual(result["linux-yocto"]["CVE-2026-1002"][0], "Unpatched")
        # The setting does not cover the RT kernel, so nothing is filtered.
        self.assertEqual(result["linux-yocto-rt"]["CVE-2026-1001"][0], "Unpatched")

    def test_without_the_build_nothing_is_filtered(self):
        self.jetson(rt_vex=[])
        self.run_feed_sbom(compiled=())
        result = self.scan()
        self.assertEqual(result["linux-yocto"]["CVE-2026-1001"][0], "Unpatched")

    def test_an_rt_only_statement_never_reaches_the_stock_kernel(self):
        self.jetson(rt_vex=[("CVE-2026-1003", "Patched", "backported-patch")])
        self.run_feed_sbom()
        result = self.scan()
        self.assertEqual(result["linux-yocto"]["CVE-2026-1003"][0], "Unpatched")
        self.assertNotIn("linux-yocto-rt", result)

    def test_kept_in_one_document_the_scanner_shares_the_statement(self):
        # What the overlap check prevents: with it bypassed, the RT kernel's
        # backport marks the stock kernel patched.
        self.jetson(rt_vex=[("CVE-2026-1003", "Patched", "backported-patch")])
        real = feedsbom.drop_vex_overlap
        feedsbom.drop_vex_overlap = lambda included, alt, default: (included, [])
        self.addCleanup(setattr, feedsbom, "drop_vex_overlap", real)
        self.run_feed_sbom()
        result = self.scan()
        self.assertEqual(result["linux-yocto-rt"]["CVE-2026-1003"][0], "Patched")
        self.assertEqual(result["linux-yocto"]["CVE-2026-1003"][0], "Patched")

    def test_the_same_statements_scan_each_kernel_on_its_own_terms(self):
        same = [("CVE-2026-1002", "Ignored", "cpe-incorrect")]
        self.jetson(rt_vex=same, default_vex=same)
        self.run_feed_sbom()
        result = self.scan()
        for kernel in ("linux-yocto", "linux-yocto-rt"):
            self.assertEqual(result[kernel]["CVE-2026-1002"], ("Ignored", "cpe-incorrect"))
            self.assertEqual(result[kernel]["CVE-2026-1003"][0], "Unpatched")
        self.assertEqual(result["linux-yocto"]["CVE-2026-1001"][0], "Ignored")
        self.assertEqual(result["linux-yocto-rt"]["CVE-2026-1001"][0], "Unpatched")

    # Jetson: an edk2 CVE the firmware has a statement about, and a
    # jetson_linux CVE nothing does.
    TEGRA_RECORDS = (
        ("CVE-2026-2001", [], {"cpe": "cpe:2.3:a:tianocore:edk2:*:*:*:*:*:*:*:*",
                               "less_than": "202599"}),
        ("CVE-2026-2002", [], {"cpe": "cpe:2.3:a:nvidia:jetson_linux:*:*:*:*:*:*:*:*",
                               "less_than": "39.9.9"}))

    BOTH_SIDES = {"jetson-rt": [("CVE-2026-2001", "Ignored", "cpe-incorrect")]}

    def tegra_scan(self, alt_vex=None, bypass=False):
        if bypass:
            real = feedsbom.drop_vex_overlap
            feedsbom.drop_vex_overlap = lambda included, alt, default: (included, [])
            self.addCleanup(setattr, feedsbom, "drop_vex_overlap", real)
        _document, coverage = self.tegra(alt_vex=alt_vex)
        listed = self.scan(self.TEGRA_RECORDS, entries=True)
        oot = [issues for name, _v, issues in listed if name == "nvidia-kernel-oot"]
        firmware, = [issues for name, _v, issues in listed if name == "edk2-firmware-tegra"]
        return coverage, oot, firmware

    def test_the_firmware_statement_never_reaches_the_module_recipe(self):
        coverage, oot, firmware = self.tegra_scan()
        self.assertEqual(len(coverage["alt_included"]), 3)
        self.assertEqual(firmware["CVE-2026-2001"][0], "Patched")
        # One build per multiconfig, each matched to the jetson_linux CVE only.
        self.assertEqual(len(oot), 4)
        for issues in oot:
            self.assertNotIn("CVE-2026-2001", issues)
            self.assertEqual(issues["CVE-2026-2002"][0], "Unpatched")

    def test_a_record_naming_both_products_reaches_every_module_build_alike(self):
        # The scanner gives the firmware's fix to every nvidia-kernel-oot build
        # once a record names jetson_linux too; the alternates stay because
        # their twin, the default build, gets exactly the same.
        records = ((self.TEGRA_RECORDS[0][0], [],
                    dict(self.TEGRA_RECORDS[0][2],
                         also=[("cpe:2.3:a:nvidia:jetson_linux:*:*:*:*:*:*:*:*", "39.9.9")])),
                   self.TEGRA_RECORDS[1])
        _document, coverage = self.tegra()
        self.assertEqual(len(coverage["alt_included"]), 3)
        listed = self.scan(records, entries=True)
        oot = [issues for name, _v, issues in listed if name == "nvidia-kernel-oot"]
        self.assertEqual(len(oot), 4)
        self.assertEqual(oot[0]["CVE-2026-2001"][0], "Patched")
        self.assertEqual(oot, [oot[0]] * 4)

    def test_without_the_check_the_scanner_still_keeps_them_apart(self):
        # What makes the narrower check safe: version alone does not carry a
        # statement to a build the CVE is not matched to.
        _coverage, oot, _firmware = self.tegra_scan(bypass=True)
        self.assertEqual(len(oot), 4)
        for issues in oot:
            self.assertNotIn("CVE-2026-2001", issues)

    def test_a_statement_on_both_sides_carries_the_firmware_status_to_every_module(self):
        # What the check still prevents: with the module recipe's own
        # statement about the firmware CVE left in, the scanner matches that CVE
        # to every nvidia-kernel-oot build and the firmware's fix wins.
        _coverage, oot, _firmware = self.tegra_scan(alt_vex=self.BOTH_SIDES, bypass=True)
        self.assertEqual([issues["CVE-2026-2001"][0] for issues in oot], ["Patched"] * 4)

    def test_with_the_check_that_module_build_is_left_out_and_nothing_leaks(self):
        coverage, oot, _firmware = self.tegra_scan(alt_vex=self.BOTH_SIDES)
        self.assertEqual([e["mc"] for e in coverage["alt_not_covered"]], ["jetson-rt"])
        self.assertEqual(len(oot), 3)
        for issues in oot:
            self.assertNotIn("CVE-2026-2001", issues)


if __name__ == "__main__":
    unittest.main()
