#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""Feed scope on scarthgap: one package document per recipe, and an alternate
kernel kept on its own build.

scarthgap's create-spdx-3.0 has no recipe-level package, so do_feed_sbom roots
the feed document at one package document of each recipe. Both kernels of a
multi-kernel machine write their documents under the same names and carry the
same identity aliases, so the alternate kernel's documents get aliases of their
own (avocado_sbom.spdxalias) before they are deserialized.

SpdxAliasTest is plain logic and always runs. RealLibTest writes a default tree
and an alternate multiconfig's tree with scarthgap OE-core's own oe.sbom30, runs
the recipe's do_feed_sbom on them and reads the document it writes; it runs when
OE_CORE_LIB names scarthgap OE-core's meta/lib.

  cd meta-avocado-sbom/tests && PYTHONPATH=../lib python3 -m unittest discover -p 'test_*.py'
"""

import copy
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import textwrap
import types
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "lib"))

from avocado_sbom import feedcheck, spdxalias  # noqa: E402

RECIPE = HERE.parent / "recipes-avocado" / "avocado-cve-report" / "avocado-cve-report.bb"

DOC_ALIAS = (spdxalias.DOC_ALIAS_PREFIX + "linux-raspberrypi/recipe-linux-raspberrypi/"
             "linux-raspberrypi/UNIHASH/document/recipe-linux-raspberrypi")
OTHER_ALIAS = (spdxalias.DOC_ALIAS_PREFIX + "openssl-native/recipe-openssl-native/"
               "openssl-native/UNIHASH/document/recipe-openssl-native")


def alias_doc(doc_alias, refs):
    """A parsed document whose SpdxDocument carries doc_alias and whose one
    relationship refers to each of refs."""
    return {
        "@context": "https://spdx.org/rdf/3.0.1/spdx-context.jsonld",
        "@graph": [
            {"type": "SpdxDocument", "spdxId": "http://x/doc",
             "extension": [{"type": spdxalias.ALIAS_TYPE, spdxalias.ALIAS_KEY: doc_alias}]},
            {"type": "Relationship", "spdxId": "http://x/rel",
             "from": refs[0], "to": refs[1:], "relationshipType": "hasOutput"},
        ],
    }


class SpdxAliasTest(unittest.TestCase):
    def test_element_prefix_hashes_the_document_alias(self):
        self.assertEqual(
            spdxalias.element_prefix(DOC_ALIAS),
            spdxalias.ALIAS_PREFIX + hashlib.sha256(DOC_ALIAS.encode()).hexdigest() + "/")

    def test_document_alias_is_read_from_the_document_node(self):
        self.assertEqual(spdxalias.document_alias(alias_doc(DOC_ALIAS, ["a"])), DOC_ALIAS)

    def test_document_alias_absent(self):
        doc = alias_doc(DOC_ALIAS, ["a"])
        doc["@graph"][0]["extension"] = []
        for data in (doc, {}, {"@graph": "x"}, [], None):
            with self.subTest(data=data):
                self.assertIsNone(spdxalias.document_alias(data))

    def test_document_alias_ignores_other_nodes_and_extensions(self):
        doc = alias_doc(DOC_ALIAS, ["a"])
        doc["@graph"][0]["extension"].insert(0, {"type": "http://other", spdxalias.ALIAS_KEY: "no"})
        doc["@graph"][1]["extension"] = [{"type": spdxalias.ALIAS_TYPE, spdxalias.ALIAS_KEY: "rel"}]
        self.assertEqual(spdxalias.document_alias(doc), DOC_ALIAS)

    def test_multiconfig_alias_cannot_be_a_pn(self):
        new = spdxalias.multiconfig_alias(DOC_ALIAS, "raspberrypi-6_6")
        self.assertEqual(new, spdxalias.DOC_ALIAS_PREFIX + "multiconfig:raspberrypi-6_6/"
                         + DOC_ALIAS[len(spdxalias.DOC_ALIAS_PREFIX):])
        self.assertNotEqual(spdxalias.multiconfig_alias(DOC_ALIAS, "other"), new)

    def test_map_holds_each_alias_and_its_prefix(self):
        mapping = spdxalias.multiconfig_map([DOC_ALIAS, None, ""], "mc")
        new = spdxalias.multiconfig_alias(DOC_ALIAS, "mc")
        self.assertEqual(mapping, {
            DOC_ALIAS: new,
            spdxalias.element_prefix(DOC_ALIAS): spdxalias.element_prefix(new),
        })

    def test_remap_rewrites_aliases_of_mapped_documents_only(self):
        mine = spdxalias.element_prefix(DOC_ALIAS)
        other = spdxalias.element_prefix(OTHER_ALIAS)
        data = alias_doc(DOC_ALIAS, [mine + "linux-raspberrypi/UNIHASH/build/recipe",
                                     other + "openssl-native/UNIHASH/build/recipe",
                                     "http://spdx.org/spdxdocs/linux/abc/package/kernel"])
        before = copy.deepcopy(data)
        mapping = spdxalias.multiconfig_map([DOC_ALIAS], "mc")
        out = spdxalias.remap(data, mapping)
        self.assertEqual(data, before, "the input is left as it was")
        new_prefix = spdxalias.element_prefix(spdxalias.multiconfig_alias(DOC_ALIAS, "mc"))
        rel = out["@graph"][1]
        self.assertEqual(rel["from"], new_prefix + "linux-raspberrypi/UNIHASH/build/recipe")
        self.assertEqual(rel["to"], before["@graph"][1]["to"])
        self.assertEqual(out["@graph"][0]["extension"][0][spdxalias.ALIAS_KEY],
                         spdxalias.multiconfig_alias(DOC_ALIAS, "mc"))
        self.assertEqual(out["@context"], before["@context"])

    def test_remap_leaves_keys_and_non_strings(self):
        mine = spdxalias.element_prefix(DOC_ALIAS)
        data = {mine + "k": [1, None, True, {"x": 2.5}]}
        self.assertEqual(spdxalias.remap(data, spdxalias.multiconfig_map([DOC_ALIAS], "mc")), data)

    def test_remap_needs_the_whole_prefix(self):
        mine = spdxalias.element_prefix(DOC_ALIAS)
        mapping = spdxalias.multiconfig_map([DOC_ALIAS], "mc")
        for value in (mine[:-1], mine[:-1] + "0/x", spdxalias.ALIAS_PREFIX + "nohash"):
            with self.subTest(value=value):
                self.assertEqual(spdxalias.remap(value, mapping), value)


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
                     arch="raspberrypi5", link_build=True):
        """recipes/recipe-<pn> and packages-staging/package-<name>, as
        scarthgap's create_spdx writes them: the build and the CVE elements in
        the recipe document, each package naming them by alias."""
        sbom30, spdx30 = self.oe.sbom30, self.oe.spdx30
        d = self.datastore(tmp, pn, unihash, arch)
        deploy = Path(d.getVar("DEPLOY_DIR_SPDX"))
        build_objset = sbom30.ObjectSet.new_objset(d, "recipe-" + pn)
        build = build_objset.new_task_build("recipe", "recipe")
        build_objset.set_element_alias(build)
        build_objset.doc.rootElement.append(build)
        vulns = []
        for cve in cves:
            v = build_objset.new_cve_vuln(cve)
            build_objset.set_element_alias(v)
            vulns.append(v)
        for dep in deps:
            build_objset.new_scoped_relationship(
                [build], spdx30.RelationshipType.dependsOn, spdx30.LifecycleScopeType.build, [dep])
        for name in packages:
            pkg_objset = sbom30.ObjectSet.new_objset(d, "package-" + name)
            pkg = pkg_objset.add_root(spdx30.software_Package(
                _id=pkg_objset.new_spdxid("package", name),
                creationInfo=pkg_objset.doc.creationInfo, name=name,
                software_packageVersion=version,
                software_primaryPurpose=spdx30.software_SoftwarePurpose.install))
            pkg.externalIdentifier.append(spdx30.ExternalIdentifier(
                externalIdentifierType=spdx30.ExternalIdentifierType.cpe23,
                identifier="cpe:2.3:*:*:%s:%s:*:*:*:*:*:*:*" % (pn, version)))
            if link_build:
                pkg_objset.new_scoped_relationship(
                    [sbom30.get_element_link_id(build)], spdx30.RelationshipType.hasOutput,
                    spdx30.LifecycleScopeType.build, [pkg])
            for v in vulns:
                pkg_objset.new_vex_patched_relationship([sbom30.get_element_link_id(v)], [pkg])
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
