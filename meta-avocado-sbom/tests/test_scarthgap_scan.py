#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""What this layer changes in the sbom-cve-check stack to run on scarthgap.

The recipes and classes come from OE-core, which on scarthgap has none of
them. These are the parts that differ from OE-core's or from the wrynose
layer's, each read straight from the file that carries it:

  - avocado-cve-report is skipped at world scope, since scarthgap OE-core has
    no meta-world-recipe-sbom to scan; feed scope builds its own document from
    package documents instead (test_feedsbom_scarthgap.py);
  - the CVE databases unpack into S, since scarthgap's fetcher has no
    UNPACKDIR;
  - the NVD database's license, cve-tou, comes from the database itself
    (NO_GENERIC_LICENSE), since scarthgap's common-licenses lacks it;
  - spdx-python-model installs the published wheel instead of building the
    sdist, whose build backend scarthgap cannot provide.

  cd meta-avocado-sbom/tests && PYTHONPATH=../lib python3 -m unittest discover -p 'test_*.py'
"""

import os
import re
import tempfile
import textwrap
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
LAYER = os.path.normpath(os.path.join(HERE, ".."))
REPORT_BB = os.path.join(LAYER, "recipes-avocado", "avocado-cve-report",
                         "avocado-cve-report.bb")
DB_DIR = os.path.join(LAYER, "recipes-devtools", "sbom-cve-check")
DB_INC = os.path.join(DB_DIR, "sbom-cve-check-update-db.inc")
MODEL_BB = os.path.join(LAYER, "recipes-devtools", "python",
                        "python3-spdx-python-model_0.0.6.bb")
LAYER_CONF = os.path.join(LAYER, "conf", "layer.conf")


def read(path):
    with open(path) as f:
        return f.read()


def python_function(path, header):
    """The body of a python function in a recipe or class, as a callable
    taking (d, bb) - the names a bitbake python function sees."""
    text = read(path)
    m = re.search(r"^%s \{\n(.*?)^\}" % re.escape(header), text, re.M | re.S)
    assert m, "%s not found in %s" % (header, path)
    ns = {}
    exec("def run(d, bb):\n" + textwrap.indent(textwrap.dedent(m.group(1)), "    "), ns)
    return ns["run"]


class SkipRecipe(Exception):
    pass


class Fatal(Exception):
    pass


def fake_bb(fetch=None, tasks=None):
    def fatal(msg):
        raise Fatal(msg)

    def addtask(task, before, after, d):
        tasks.append((task, before, after))
    return types.SimpleNamespace(
        parse=types.SimpleNamespace(SkipRecipe=SkipRecipe),
        fatal=fatal,
        fetch2=fetch,
        build=types.SimpleNamespace(addtask=addtask),
    )


class Data:
    def __init__(self, **values):
        self.values = values
        self.flags = {}

    def getVar(self, name):
        return self.values.get(name)

    def appendVarFlag(self, var, flag, value):
        self.flags[(var, flag)] = self.flags.get((var, flag), "") + value

    def setVarFlag(self, var, flag, value):
        self.flags[(var, flag)] = value


class ReportScopeTests(unittest.TestCase):
    def run_anonymous(self, **values):
        d = Data(**values)
        d.tasks = []
        python_function(REPORT_BB, "python ()")(d, fake_bb(tasks=d.tasks))
        return d

    def test_world_scope_skips_the_recipe(self):
        with self.assertRaises(SkipRecipe) as cm:
            self.run_anonymous(AVOCADO_CVE_SCOPE="world")
        self.assertIn("kas/feature/cve-check-feed.yml", str(cm.exception))
        self.assertIn("kas/feature/cve-check-image.yml", str(cm.exception))

    def test_world_is_still_the_default(self):
        # A build that stacks cve-check.yml alone gets the skip, not a scan of
        # an image whose class it never added.
        self.assertRegex(read(REPORT_BB), r'(?m)^AVOCADO_CVE_SCOPE \?= "world"$')

    def test_image_scope_reads_the_image_scan(self):
        d = self.run_anonymous(AVOCADO_CVE_SCOPE="image",
                               AVOCADO_CVE_IMAGE="avocado-image-rootfs")
        self.assertEqual(d.flags[("do_cve_report", "depends")],
                         " avocado-image-rootfs:do_sbom_cve_check")

    def test_image_scope_adds_no_feed_task(self):
        d = self.run_anonymous(AVOCADO_CVE_SCOPE="image",
                               AVOCADO_CVE_IMAGE="avocado-image-rootfs")
        self.assertEqual(d.tasks, [])

    def test_feed_scope_runs_its_own_tasks(self):
        d = self.run_anonymous(AVOCADO_CVE_SCOPE="feed",
                               SBOM_CVE_CHECK_UPDATE_DB_DEPENDENCIES=" db-native:do_patch")
        self.assertEqual(d.tasks, [("do_feed_sbom", "do_cve_report", None),
                                   ("do_feed_scan", "do_cve_report", "do_feed_sbom")])
        self.assertNotIn(("do_cve_report", "depends"), d.flags)
        self.assertEqual(d.flags[("do_feed_sbom", "nostamp")], "1")
        self.assertEqual(d.flags[("do_feed_scan", "nostamp")], "1")
        self.assertEqual(d.flags[("do_feed_scan", "depends")].split(),
                         ["python3-sbom-cve-check-native:do_populate_sysroot",
                          "db-native:do_patch"])

    def test_an_unknown_scope_is_fatal(self):
        with self.assertRaises(Fatal):
            self.run_anonymous(AVOCADO_CVE_SCOPE="bogus")

    def test_the_recipe_uses_the_layer_nospdx(self):
        # avocado-nospdx also deletes the runtime SPDX task scarthgap's nospdx
        # misses (meta-avocado/classes/avocado-nospdx.bbclass).
        self.assertRegex(read(REPORT_BB), r"(?m)^inherit nopackages avocado-nospdx$")


class DatabaseUnpackTests(unittest.TestCase):
    def test_s_is_the_database_directory(self):
        self.assertRegex(
            read(DB_INC),
            r'(?m)^S = "\$\{SBOM_CVE_CHECK_DEPLOY_DB_DIR\}/\$\{SBOM_CVE_CHECK_DB_NAME\}"$')

    def test_no_unpackdir(self):
        # scarthgap's fetcher never reads it, so setting it would only look
        # like it worked.
        self.assertNotRegex(read(DB_INC), r"(?m)^UNPACKDIR\b")

    def test_do_unpack_unpacks_into_s(self):
        roots = []

        class Fetch:
            def __init__(self, urls, d):
                self.urls = urls

            def unpack(self, root):
                roots.append((self.urls, root))

        fetch2 = types.SimpleNamespace(Fetch=Fetch, BBFetchException=Exception)
        d = Data(SRC_URI="git://example.com/db.git;branch=main;destsuffix=",
                 S="/deploy/sbom-cve-check/databases/nvd-fkie")
        python_function(DB_INC, "python do_unpack()")(d, fake_bb(fetch2))
        self.assertEqual(roots, [(["git://example.com/db.git;branch=main;destsuffix="],
                                  "/deploy/sbom-cve-check/databases/nvd-fkie")])

    def test_a_fetch_error_is_fatal(self):
        class Broken(Exception):
            pass

        class Fetch:
            def __init__(self, urls, d):
                raise Broken("no network")

        fetch2 = types.SimpleNamespace(Fetch=Fetch, BBFetchException=Broken)
        d = Data(SRC_URI="git://example.com/db.git", S="/s")
        with self.assertRaises(Fatal):
            python_function(DB_INC, "python do_unpack()")(d, fake_bb(fetch2))

    def test_both_database_recipes_unpack_with_an_empty_destsuffix(self):
        # The clone lands in S itself only with destsuffix empty; the git
        # fetcher's default would put it in S/git/.
        recipes = [f for f in os.listdir(DB_DIR) if f.startswith("sbom-cve-check-update-")
                   and f.endswith(".bb")]
        self.assertEqual(len(recipes), 2, recipes)
        for name in recipes:
            text = read(os.path.join(DB_DIR, name))
            with self.subTest(recipe=name):
                self.assertRegex(text, r'(?m)^SRC_URI = "git://[^"]*;destsuffix="$')
                self.assertRegex(text, r"(?m)^require sbom-cve-check-update-db\.inc$")


class LicenseTests(unittest.TestCase):
    def test_a_database_license_without_a_generic_text_names_its_own_file(self):
        for name in os.listdir(DB_DIR):
            if not name.endswith(".bb"):
                continue
            text = read(os.path.join(DB_DIR, name))
            lic = re.search(r'(?m)^LICENSE = "([^"]+)"$', text).group(1)
            if lic in ("MIT", "GPL-2.0-or-later"):
                continue
            with self.subTest(recipe=name, license=lic):
                chksum = re.search(r'(?m)^LIC_FILES_CHKSUM = "file://([^;"]+)', text).group(1)
                self.assertIn('NO_GENERIC_LICENSE[%s] = "%s"' % (lic, chksum), text)



class ScannerRecipeTests(unittest.TestCase):
    def test_the_target_package_pulls_in_the_standard_library(self):
        # On a target image python3-core alone lacks logging and json, which
        # the tool imports at startup, and the database backend runs git.
        text = read(os.path.join(DB_DIR, "python3-sbom-cve-check_1.4.0.bb"))
        self.assertRegex(text, r'(?m)^RDEPENDS:\$\{PN\}:append:class-target = " python3-modules git"$')
        self.assertNotRegex(text, r'(?m)^RDEPENDS:\$\{PN\}(:append)? *\+?= *"[^"]*python3-modules')


class SpdxPythonModelTests(unittest.TestCase):
    def setUp(self):
        self.text = read(MODEL_BB)

    def test_fetches_the_wheel_as_a_zip(self):
        # downloadfilename .zip is what makes the fetcher unzip it and
        # base.bbclass add unzip-native to do_unpack.
        m = re.search(r'(?m)^PYPI_SRC_URI = "([^"]+)"$', self.text)
        self.assertTrue(m)
        uri = m.group(1)
        self.assertIn("-py3-none-any.whl;", uri)
        self.assertIn(";downloadfilename=${PYPI_PACKAGE}-${PV}-py3-none-any.zip", uri)
        self.assertIn(";subdir=${PYPI_PACKAGE}-${PV}", uri)

    def test_installs_the_package_and_its_metadata(self):
        install = re.search(r"(?ms)^do_install\(\) \{\n(.*?)^\}", self.text).group(1)
        self.assertIn("${S}/spdx_python_model ", install)
        self.assertIn("${S}/spdx_python_model-${PV}.dist-info", install)
        self.assertIn("${D}${PYTHON_SITEPACKAGES_DIR}", install)

    def test_the_license_is_read_from_the_wheel(self):
        self.assertIn("file://spdx_python_model-${PV}.dist-info/licenses/LICENSE;",
                      self.text)

    @unittest.skipUnless(os.environ.get("SPDX_PYTHON_MODEL_WHEEL"),
                         "set SPDX_PYTHON_MODEL_WHEEL to a downloaded wheel to check it")
    def test_the_wheel_holds_what_do_install_copies(self):
        import zipfile
        names = zipfile.ZipFile(os.environ["SPDX_PYTHON_MODEL_WHEEL"]).namelist()
        tops = {n.split("/", 1)[0] for n in names}
        self.assertEqual(tops, {"spdx_python_model", "spdx_python_model-0.0.6.dist-info"})
        self.assertIn("spdx_python_model-0.0.6.dist-info/licenses/LICENSE", names)


if __name__ == "__main__":
    unittest.main()
