#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""do_kernel_cve_improve filters a kernel only on a list of its own tree.

improve_kernel_cve_report.py files a CVE as not compiled when none of the
CNA's programFiles is in the compiled-source list, compared by exact path.
Every recipe SPDX document lists its SRC_URI files as sources, so a kernel
built without debug info passes "has sources" and comes out with every
in-range CVE that names its files not compiled.

  python3 -m unittest discover -s meta-avocado-sbom/tests -p 'test_*.py'
"""

import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

from avocado_sbom import report  # noqa: E402

FIXTURES = os.path.join(HERE, "fixtures", "kernel-spdx")
RECIPE = os.path.join(HERE, "..", "recipes-avocado", "avocado-cve-report",
                      "avocado-cve-report.bb")


def load(name):
    with open(os.path.join(FIXTURES, name)) as f:
        return json.load(f)


def gate(doc):
    return report.is_kernel_tree(report.spdx_compiled_sources(doc))


def spdx22(*files):
    return {"spdxVersion": "SPDX-2.2",
            "files": [{"fileName": name, "fileTypes": types}
                      for name, types in files]}


class KernelFilterGate(unittest.TestCase):
    def test_a_kernel_listing_only_its_src_uri_is_not_filtered(self):
        doc = load("recipe-kernel-no-debuginfo-3.0.1.spdx.json")
        compiled = report.spdx_compiled_sources(doc)
        # The old gate's question, still true here: it has sources.
        self.assertTrue(compiled)
        self.assertFalse(report.is_kernel_tree(compiled))

    def test_a_kernel_listing_its_tree_is_filtered(self):
        self.assertTrue(gate(load("recipe-kernel-3.0.1.spdx.json")))

    def test_paths_are_normalized_as_the_script_does(self):
        compiled = report.spdx_compiled_sources(
            load("recipe-kernel-3.0.1.spdx.json"))
        self.assertIn("init/main.c", compiled)
        self.assertIn("drivers/net/ethernet/intel/e1000/e1000_main.c", compiled)
        # A name without "/" is kept whole.
        self.assertIn("defconfig", compiled)

    def test_one_tree_file_is_enough(self):
        for path in ("init/main.c", "include/linux/module.h"):
            with self.subTest(path=path):
                self.assertTrue(gate({"@graph": [
                    {"software_primaryPurpose": "source",
                     "name": "linux-6.6/%s" % path}]}))

    def test_a_tree_one_level_too_deep_is_not_filtered(self):
        # Only the first component is dropped, so these never equal a
        # programFiles path.
        self.assertFalse(gate({"@graph": [
            {"software_primaryPurpose": "source",
             "name": "build/linux-6.6/%s" % path}
            for path in report.KERNEL_TREE_SOURCES]}))

    def test_tree_files_that_are_not_sources_do_not_count(self):
        self.assertFalse(gate({"@graph": [
            {"software_primaryPurpose": "patch",
             "name": "linux-6.6/init/main.c"}]}))

    def test_spdx_2_2(self):
        self.assertTrue(gate(spdx22(
            ("defconfig", ["SOURCE"]),
            ("linux-6.6/include/linux/module.h", ["SOURCE"]))))
        self.assertFalse(gate(spdx22(
            ("defconfig", ["SOURCE"]),
            ("linux-6.6/init/main.c", ["BINARY"]))))

    def test_mod_c_alone_is_not_enough(self):
        self.assertFalse(gate({"@graph": [
            {"software_primaryPurpose": "source",
             "name": "build/linux-6.6/drivers/net/foo.mod.c"}]}))

    def test_a_malformed_document_has_no_sources(self):
        for doc in ({"@graph": None}, {"spdxVersion": "SPDX-2.2", "files": None}, [], None):
            with self.subTest(doc=doc):
                self.assertEqual(report.spdx_compiled_sources(doc), set())

    def test_no_sources(self):
        self.assertFalse(gate({"@graph": []}))
        self.assertFalse(gate(spdx22()))
        self.assertFalse(gate({}))


class RecipeUsesTheGate(unittest.TestCase):
    """Runs the recipe's _improve_kernel_cve with bitbake faked out."""

    MACHINE = "avocado-test"
    KERNEL = "linux-test"

    def setUp(self):
        with open(RECIPE) as f:
            text = f.read()
        start = text.index("def _improve_kernel_cve(")
        end = text.index("\npython do_kernel_cve_improve()", start)
        self.logs = []

        def log(level):
            return lambda msg: self.logs.append((level, msg))

        def fatal(msg):
            raise AssertionError("bb.fatal: %s" % msg)

        bb = types.SimpleNamespace(
            note=log("note"), warn=log("warn"), plain=log("plain"),
            fatal=fatal,
            utils=types.SimpleNamespace(
                mkdirhier=lambda p: os.makedirs(p, exist_ok=True),
                remove=lambda p: os.path.exists(p) and os.remove(p)))
        ns = {"os": os, "bb": bb}
        exec(compile(text[start:end], RECIPE, "exec"), ns)
        self.improve = ns["_improve_kernel_cve"]

        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.cve_dir = os.path.join(self.tmp, "cve")
        os.makedirs(self.cve_dir)
        with open(os.path.join(self.cve_dir, "%s_cve.json" % self.KERNEL),
                  "w") as f:
            json.dump({"package": [{"name": self.KERNEL,
                                    "version": "6.6.63", "issue": []}]}, f)
        self.spdx_dir = os.path.join(self.tmp, "spdx")
        self.overlay = os.path.join(self.cve_dir, report.OVERLAY_DIRNAME,
                                    "%s_cve.json" % self.KERNEL)
        values = {"MACHINE": self.MACHINE, "CVE_CHECK_DIR": self.cve_dir,
                  "STAGING_LIBDIR_NATIVE": self.tmp}
        self.d = types.SimpleNamespace(getVar=values.get)

    def run_on(self, fixture, alt):
        recipes = os.path.join(self.spdx_dir, self.MACHINE.replace("-", "_"),
                               "recipes")
        os.makedirs(recipes)
        shutil.copy(os.path.join(FIXTURES, fixture),
                    os.path.join(recipes, "recipe-%s.spdx.json" % self.KERNEL))

        def script(cmd, **kwargs):
            with open(cmd[cmd.index("--new-cve-report") + 1], "w") as f:
                f.write("{}")
            return types.SimpleNamespace(stderr="")

        with mock.patch("subprocess.run", side_effect=script) as run:
            self.improve(self.d, self.KERNEL, self.cve_dir, self.spdx_dir,
                         os.path.join(self.tmp, "vulns"), "script.py", alt)
        return run

    def levels(self):
        return [level for level, _ in self.logs]

    def test_a_kernel_listing_only_its_src_uri_is_left_alone(self):
        run = self.run_on("recipe-kernel-no-debuginfo-3.0.1.spdx.json",
                          alt=False)
        run.assert_not_called()
        self.assertFalse(os.path.exists(self.overlay))
        self.assertEqual(self.levels(), ["warn"])

    def test_an_alternate_kernel_left_alone_is_a_note(self):
        run = self.run_on("recipe-kernel-no-debuginfo-3.0.1.spdx.json",
                          alt=True)
        run.assert_not_called()
        self.assertFalse(os.path.exists(self.overlay))
        self.assertEqual(self.levels(), ["note"])

    def test_a_kernel_listing_its_tree_is_filtered(self):
        run = self.run_on("recipe-kernel-3.0.1.spdx.json", alt=True)
        run.assert_called_once()
        self.assertTrue(os.path.exists(self.overlay))
        self.assertEqual(self.levels(), [])


if __name__ == "__main__":
    unittest.main()
