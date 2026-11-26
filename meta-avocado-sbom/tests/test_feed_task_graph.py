#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""What the feed tasks schedule, and the sysroot do_feed_scan gets from it.

OE-Core's extend_recipe_sysroot installs into a task's sysroot the
do_populate_sysroot of every task it reaches through tasks that are not sstate
tasks, as if each were a direct dependency. A feed task that waits for a feed
target's do_build therefore hands every task after it the sysroots of the
targets and of what their do_build waits for, and avocado-distro's
do_populate_sysroot is noexec, so there is no manifest to install and the task
fails. These tests build a small feed's task graph the way bitbake would from
this recipe's own task flags (recrdeptask and recideptask as runqueue.py
resolves them), then run OE-Core's own extend_recipe_sysroot and
setscene_depvalid for do_feed_scan, read from the pinned OE-Core named by
OE_CORE_LIB (its meta/lib).

  cd meta-avocado-sbom/tests && OE_CORE_LIB=<oe-core>/meta/lib \\
      PYTHONPATH=../lib python3 -m unittest test_feed_task_graph
"""

import os
import re
import tempfile
import textwrap
import types
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
RECIPE = HERE.parent / "recipes-avocado" / "avocado-cve-report" / "avocado-cve-report.bb"
LAYERS = HERE.parent.parent
PN = "avocado-cve-report"
# scarthgap OE-Core has no recipe-level SPDX task, and every recipe's build is
# in its feed document; its recipe inherits this layer's avocado-nospdx.
LINE = ("scarthgap" if re.search(r"(?m)^inherit nopackages avocado-nospdx$", RECIPE.read_text())
        else "wrynose")
# The SPDX tasks OE-Core's image SBOM task asks for on each line.
IMAGE_SPDX_TASKS = {"wrynose": "do_create_recipe_spdx do_create_spdx do_create_package_spdx",
                    "scarthgap": "do_create_spdx do_create_package_spdx"}[LINE]

SSTATETASKS = "do_populate_sysroot do_package do_packagedata do_package_write_rpm " + \
    IMAGE_SPDX_TASKS


class Fatal(Exception):
    pass


class SkipRecipe(Exception):
    pass


def oe_meta():
    lib = os.environ.get("OE_CORE_LIB")
    return Path(lib).parent if lib else None


# --- The recipe's own task flags --------------------------------------------

class Data:
    def __init__(self, **values):
        self.values = values
        self.flags = {}
        self.tasks = []

    def getVar(self, name, expand=True):
        return self.values.get(name)

    def appendVarFlag(self, var, flag, value):
        self.flags[(var, flag)] = self.flags.get((var, flag), "") + value

    def setVarFlag(self, var, flag, value):
        self.flags[(var, flag)] = value


def recipe_flags(**values):
    """The tasks and flags the recipe's anonymous python sets."""
    m = re.search(r"^python \(\) \{\n(.*?)^\}", RECIPE.read_text(), re.M | re.S)
    d = Data(**values)

    def fatal(msg):
        raise Fatal(msg)
    bb = types.SimpleNamespace(
        fatal=fatal, parse=types.SimpleNamespace(SkipRecipe=SkipRecipe),
        build=types.SimpleNamespace(
            addtask=lambda task, before, after, d: d.tasks.append((task, before, after)),
            deltask=lambda task, d: d.tasks.append(("deleted", task))))
    ns = {}
    exec("def run(d, bb):\n" + textwrap.indent(textwrap.dedent(m.group(1)), "    "), ns)
    ns["run"](d, bb)
    return d


# The wiring that waited for a feed target's do_build, which failed in do_feed_scan.
def target_build_wiring(d):
    d.flags = {k: v for k, v in d.flags.items()
               if k[0] not in ("do_feed_sbom", "do_feed_builds", "do_feed_targets")}
    d.tasks = [t for t in d.tasks if t[0] not in ("do_feed_builds", "do_feed_targets")]
    d.flags[("do_feed_sbom", "depends")] = " avocado-distro:do_build"
    d.flags[("do_feed_sbom", "recrdeptask")] = " " + IMAGE_SPDX_TASKS
    if d.values.get("AVOCADO_MULTIKERNEL_MC_RECIPES"):
        d.flags[("do_feed_sbom", "depends")] += " avocado-distro:do_multikernel_merge"
    return d


# --- A small feed -----------------------------------------------------------

class Graph:
    """tid -> set of tids it depends on, tid being "<pn>:<task>"."""

    def __init__(self):
        self.deps = {}
        self.noexec = set()

    def add(self, tid, *deps):
        self.deps.setdefault(tid, set()).update(deps)
        for dep in deps:
            self.deps.setdefault(dep, set())

    def target(self, pn, depends=(), compiled=False):
        dep_sysroots = ["%s:do_populate_sysroot" % dep for dep in depends]
        self.add(pn + ":do_fetch")
        self.add(pn + ":do_unpack", pn + ":do_fetch")
        self.add(pn + ":do_patch", pn + ":do_unpack")
        self.add(pn + ":do_prepare_recipe_sysroot", pn + ":do_fetch",
                 "gcc-cross:do_populate_sysroot", *dep_sysroots)
        self.add(pn + ":do_configure", pn + ":do_patch", pn + ":do_prepare_recipe_sysroot")
        self.add(pn + ":do_compile", pn + ":do_configure")
        self.add(pn + ":do_install", pn + ":do_compile")
        self.add(pn + ":do_populate_sysroot", pn + ":do_install")
        self.add(pn + ":do_package", pn + ":do_install")
        self.add(pn + ":do_packagedata", pn + ":do_package")
        self.add(pn + ":do_package_write_rpm", pn + ":do_packagedata")
        self.spdx(pn, depends, package=True)
        self.add(pn + ":do_build", pn + ":do_populate_sysroot", pn + ":do_package_write_rpm",
                 pn + ":do_create_package_spdx")

    def native(self, pn, depends=(), fetch_depends=()):
        self.add(pn + ":do_fetch", *fetch_depends)
        self.add(pn + ":do_unpack", pn + ":do_fetch")
        self.add(pn + ":do_patch", pn + ":do_unpack")
        self.add(pn + ":do_prepare_recipe_sysroot", pn + ":do_fetch",
                 *["%s:do_populate_sysroot" % dep for dep in depends])
        self.add(pn + ":do_configure", pn + ":do_patch", pn + ":do_prepare_recipe_sysroot")
        self.add(pn + ":do_compile", pn + ":do_configure")
        self.add(pn + ":do_install", pn + ":do_compile")
        self.add(pn + ":do_populate_sysroot", pn + ":do_install")
        self.spdx(pn, depends, package=False)
        self.add(pn + ":do_build", pn + ":do_populate_sysroot", pn + ":do_create_spdx")

    def spdx(self, pn, depends, package):
        # OE-Core's create-spdx-3.0: the recipe-level task (wrynose) has no
        # ordering but its build dependencies' own; the build task follows the
        # build.
        build = [pn + ":do_populate_sysroot", pn + ":do_patch"]
        if LINE == "wrynose":
            self.add(pn + ":do_create_recipe_spdx",
                     *["%s:do_create_recipe_spdx" % dep for dep in depends])
            build.append(pn + ":do_create_recipe_spdx")
        if package:
            build += [pn + ":do_package", pn + ":do_packagedata"]
        self.add(pn + ":do_create_spdx", *build,
                 *["%s:do_create_spdx" % dep for dep in depends])
        if package:
            self.add(pn + ":do_create_package_spdx", pn + ":do_create_spdx")


def ships_no_spdx(pn):
    """Whether this layer's meta-target recipe PN inherits avocado-nospdx."""
    paths = list(LAYERS.glob("*/recipes-avocado/distro/%s.bb" % pn))
    assert len(paths) == 1, (pn, paths)
    return re.search(r"(?m)^inherit .*\bavocado-nospdx\b", paths[0].read_text()) is not None


def aggregator_spdx(g, pn):
    """A meta-target's own SPDX tasks, as create-spdx-3.0 adds them to any
    recipe that does not inherit nospdx: its build task follows the build."""
    if ships_no_spdx(pn):
        return
    build = [pn + ":do_populate_sysroot"]
    if LINE == "wrynose":
        g.add(pn + ":do_create_recipe_spdx")
        build.append(pn + ":do_create_recipe_spdx")
    g.add(pn + ":do_create_spdx", *build)
    g.add(pn + ":do_create_package_spdx", pn + ":do_create_spdx")


def feed_graph():
    """A feed: avocado-distro builds avocado-core (one package recipe, foo, and
    the kernel) and avocado-stone, whose bundle follows the kernel's deploy;
    avocado-stone's and avocado-distro's do_populate_sysroot are noexec."""
    g = Graph()
    g.native("gcc-cross")
    g.native("git-native")
    g.native("bar-native")
    g.native("kmod-native")
    g.native("python3-native")
    g.native("python3-sbom-cve-check-native", ["python3-native"])
    g.native("db-native", fetch_depends=["git-native:do_populate_sysroot"])
    g.target("foo", ["bar-native"])
    g.target("linux-yocto", ["kmod-native"])
    g.add("linux-yocto:do_deploy", "linux-yocto:do_install")
    g.add("linux-yocto:do_build", "linux-yocto:do_deploy")
    g.add("avocado-core:do_populate_sysroot")
    g.add("avocado-core:do_build", "avocado-core:do_populate_sysroot",
          "foo:do_package_write_rpm", "linux-yocto:do_package_write_rpm")
    g.add("avocado-stone:do_compile", "linux-yocto:do_deploy")
    g.add("avocado-stone:do_deploy", "avocado-stone:do_compile")
    g.add("avocado-stone:do_populate_sysroot", "avocado-stone:do_compile")
    g.add("avocado-stone:do_build", "avocado-stone:do_populate_sysroot",
          "avocado-stone:do_deploy")
    g.add("avocado-distro:do_prepare_recipe_sysroot", "gcc-cross:do_populate_sysroot")
    g.add("avocado-distro:do_configure", "avocado-distro:do_prepare_recipe_sysroot")
    g.add("avocado-distro:do_multikernel_merge", "avocado-distro:do_configure")
    g.add("avocado-distro:do_compile", "avocado-distro:do_configure",
          "avocado-distro:do_multikernel_merge", "avocado-core:do_build",
          "avocado-stone:do_build")
    g.add("avocado-distro:do_install", "avocado-distro:do_compile")
    g.add("avocado-distro:do_populate_sysroot", "avocado-distro:do_install")
    g.add("avocado-distro:do_build", "avocado-distro:do_compile",
          "avocado-distro:do_populate_sysroot")
    g.noexec |= {"avocado-distro:do_populate_sysroot", "avocado-stone:do_populate_sysroot"}
    for pn in ("avocado-distro", "avocado-stone"):
        aggregator_spdx(g, pn)
    return g


def add_recipe(g, d):
    """avocado-cve-report's tasks as bitbake builds them from the flags."""
    providers = {"virtual/kernel": "linux-yocto"}

    def tid(dep):
        pn, task = dep.rsplit(":", 1)
        return "%s:%s" % (providers.get(pn, pn), task)

    g.add(PN + ":do_cve_report")
    g.add(PN + ":do_rpm_manifest", PN + ":do_cve_report")
    g.add(PN + ":do_build", PN + ":do_cve_report", PN + ":do_rpm_manifest")
    for entry in d.tasks:
        if entry[0] == "deleted":
            continue
        task, before, after = entry
        g.add(PN + ":" + task, *([PN + ":" + after] if after else []))
        if before:
            g.add(PN + ":" + before, PN + ":" + task)
    for (task, flag), value in d.flags.items():
        if flag == "depends":
            g.add(PN + ":" + task, *[tid(dep) for dep in value.split()])
    # mcdepends name tasks of another multiconfig, which bitbake leaves out of
    # BB_TASKDEPDATA (runqueue.py filtermcdeps), so they are not modelled.

    def reach(roots):
        seen = set()
        todo = list(roots)
        while todo:
            for dep in g.deps[todo.pop()]:
                if dep not in seen:
                    seen.add(dep)
                    todo.append(dep)
        return seen

    # runqueue.py: recrdeptask adds the named tasks of every recipe the task's
    # dependencies, and those of its recideptask, reach. OE-Core's base.bbclass
    # gives every do_build one, unless the recipe replaces it.
    flags = {("do_build", "recrdeptask"): " do_deploy"}
    flags.update(d.flags)
    changed = True
    while changed:
        changed = False
        for (task, flag), value in list(flags.items()):
            if flag != "recrdeptask":
                continue
            me = PN + ":" + task
            roots = set(g.deps[me])
            idep = flags.get((task, "recideptask"))
            if idep:
                roots |= {PN + ":" + idep} | g.deps[PN + ":" + idep]
            pns = {t.rsplit(":", 1)[0] for t in roots | reach(roots)}
            for pn in pns:
                for name in value.split():
                    new = "%s:%s" % (pn, name)
                    if new != me and new in g.deps and new not in g.deps[me]:
                        g.deps[me].add(new)
                        changed = True
    return g


def scheduled(g):
    """The tasks 'bitbake avocado-cve-report' keeps: what its do_build reaches."""
    keep = {PN + ":do_build"}
    todo = [PN + ":do_build"]
    while todo:
        for dep in g.deps[todo.pop()]:
            if dep not in keep:
                keep.add(dep)
                todo.append(dep)
    return keep


def taskdepdata(g, task):
    """BB_TASKDEPDATA for a task: every task it reaches, as bitbake lists them."""
    out = {}
    todo = [task]
    while todo:
        tid = todo.pop()
        if tid in out:
            continue
        pn, name = tid.rsplit(":", 1)
        out[tid] = [pn, name, "/layers/%s.bb" % pn, set(g.deps[tid]), [pn],
                    "h-" + tid, "h-" + tid, "/layers/%s.bb" % pn]
        todo.extend(g.deps[tid])
    return out


# --- OE-Core's own code -----------------------------------------------------

def oe_function(path, pattern):
    m = re.search(pattern, path.read_text(), re.M | re.S)
    assert m, "%s not found in %s" % (pattern, path)
    return m.group(1)


def run_extend_recipe_sysroot(g, task, noexec):
    """Run OE-Core's extend_recipe_sysroot for TASK of this recipe; returns the
    recipes whose do_populate_sysroot manifest it asked for, in order. A
    noexec do_populate_sysroot has no manifest, which fails as in OE-Core."""
    meta = oe_meta()
    staging = meta / "classes-global" / "staging.bbclass"
    sstate = meta / "classes-global" / "sstate.bbclass"
    asked = []

    def fatal(msg):
        raise Fatal(msg)

    def find_sstate_manifest(pn, fn, taskname, d, multilibs):
        asked.append(pn)
        if "%s:do_%s" % (pn, taskname) in noexec:
            raise Fatal("The sstate manifest for task '%s:%s' (multilib variant '') "
                        "could not be found." % (pn, taskname))
        return None, d

    class Lock:
        pass

    bb = types.SimpleNamespace(
        fatal=fatal, note=lambda *a: None, warn=lambda *a: None,
        debug=lambda *a: None, plain=lambda *a: None,
        utils=types.SimpleNamespace(
            lockfile=lambda path: Lock(), unlockfile=lambda lock: None,
            mkdirhier=lambda path: os.makedirs(path, exist_ok=True)),
        build=types.SimpleNamespace(clean_stamp=lambda *a: None))
    oe = types.SimpleNamespace(sstatesig=types.SimpleNamespace(
        find_sstate_manifest=find_sstate_manifest))
    ns = {"bb": bb, "oe": oe, "os": os}
    exec(oe_function(sstate, r"^(def setscene_depvalid\(.*?)(?=^\S)"), ns)
    body = oe_function(staging, r"^python extend_recipe_sysroot\(\) \{\n(.*?)^\}")
    exec("def extend_recipe_sysroot(d):\n" + body, ns)

    with tempfile.TemporaryDirectory() as tmp:
        values = {
            "BB_TASKDEPDATA": taskdepdata(g, PN + ":" + task),
            "BB_RUNTASK": task, "PN": PN, "WORKDIR": tmp,
            "STAGING_DIR": tmp + "/sysroots-components",
            "COMPONENTS_DIR": tmp + "/sysroots-components",
            "RECIPE_SYSROOT": tmp + "/recipe-sysroot",
            "RECIPE_SYSROOT_NATIVE": tmp + "/recipe-sysroot-native",
            "SSTATETASKS": SSTATETASKS, "SSTATE_EXCLUDEDEPS_SYSROOT": "",
        }

        class D:
            def getVar(self, name, expand=True):
                return values.get(name)

            def setVar(self, name, value):
                values[name] = value
        ns["extend_recipe_sysroot"](D())
    return asked


def gets_a_sysroot(d, task):
    # staging_taskhandler: a task whose depends name a do_populate_sysroot
    # runs extend_recipe_sysroot first.
    return "populate_sysroot" in (d.flags.get((task, "depends")) or "")


FEEDS = {
    "single kernel": {},
    "alternate kernels": {"AVOCADO_MULTIKERNEL_MC_RECIPES":
                          "jetson-rt:linux-yocto-rt jetson-rt:nvidia-kernel-oot"},
}


def feed_values(**extra):
    values = {"AVOCADO_CVE_SCOPE": "feed", "AVOCADO_FEED_SBOM_TARGETS": "avocado-distro",
              "SBOM_CVE_CHECK_UPDATE_DB_DEPENDENCIES": " db-native:do_patch",
              "PREFERRED_PROVIDER_virtual/kernel": "linux-yocto",
              "SPDX_INCLUDE_COMPILED_SOURCES:pn-linux-yocto": "1"}
    values.update(extra)
    return values


class FeedFlagsTests(unittest.TestCase):
    """From the flags alone: no task a feed run schedules waits for another
    recipe's do_build, and only do_feed_scan, for the scanner and its
    databases, for a do_populate_sysroot."""

    SCHEDULED = ("do_feed_builds", "do_feed_sbom", "do_feed_scan", "do_cve_report",
                 "do_rpm_manifest")

    def test_report_tasks_wait_for_no_other_recipe_build_or_sysroot(self):
        for name, extra in FEEDS.items():
            with self.subTest(feed=name):
                d = recipe_flags(**feed_values(**extra))
                for task in self.SCHEDULED:
                    for flag in ("depends", "mcdepends"):
                        deps = (d.flags.get((task, flag)) or "").split()
                        self.assertFalse([dep for dep in deps if dep.endswith(":do_build")],
                                         (task, flag))
                        if task != "do_feed_scan":
                            self.assertFalse(
                                [dep for dep in deps if dep.endswith(":do_populate_sysroot")],
                                (task, flag))
                # A recursive task with mcdepends would recurse over every
                # multiconfig edge of its multiconfig: bitbake pools them.
                self.assertNotIn(("do_feed_builds", "mcdepends"), d.flags)
                self.assertEqual(
                    [dep for dep in d.flags[("do_feed_scan", "depends")].split()
                     if dep.endswith(":do_populate_sysroot")],
                    ["python3-sbom-cve-check-native:do_populate_sysroot"])

    def test_the_report_build_follows_no_recipe_recursively(self):
        # OE-Core's do_build[recrdeptask] would reach every feed recipe's
        # do_deploy through the SPDX tasks.
        for name, extra in FEEDS.items():
            with self.subTest(feed=name):
                d = recipe_flags(**feed_values(**extra))
                self.assertEqual(d.flags[("do_build", "recrdeptask")], "")

    def test_the_targets_build_is_only_read_never_scheduled(self):
        d = recipe_flags(**feed_values())
        holders = [k for k, v in d.flags.items()
                   if k[1] in ("depends", "mcdepends") and ":do_build" in v]
        self.assertEqual(holders, [("do_feed_targets", "depends")])
        # No task is ordered before or after it, so nothing reaches it.
        self.assertIn(("do_feed_targets", None, None), d.tasks)
        self.assertFalse([t for t in d.tasks if "do_feed_targets" in t[1:]])
        self.assertEqual(d.flags[("do_feed_sbom", "recideptask")], "do_feed_targets")


@unittest.skipUnless(oe_meta(), "OE_CORE_LIB not set")
class FeedSysrootTests(unittest.TestCase):
    """OE-Core's extend_recipe_sysroot over the modelled feed graph."""

    def sysroot(self, d):
        g = add_recipe(feed_graph(), d)
        self.assertTrue(gets_a_sysroot(d, "do_feed_scan"))
        return run_extend_recipe_sysroot(g, "do_feed_scan", feed_graph().noexec)

    def test_waiting_for_the_targets_build_fails_as_it_did(self):
        # Waiting for the target's do_build: avocado-distro's do_build behind do_feed_sbom
        # hands do_feed_scan the targets' sysroots, and avocado-distro's has no
        # manifest.
        for name, extra in FEEDS.items():
            with self.subTest(feed=name):
                d = target_build_wiring(recipe_flags(**feed_values(**extra)))
                with self.assertRaises(Fatal) as cm:
                    self.sysroot(d)
                self.assertIn("'avocado-distro:populate_sysroot'", str(cm.exception))

    def test_the_scan_gets_the_sysroot_it_had_before(self):
        # Before the SPDX dependencies: do_feed_sbom waited for the merge only.
        for name, extra in FEEDS.items():
            with self.subTest(feed=name):
                before = recipe_flags(**feed_values(**extra))
                before.flags = {k: v for k, v in before.flags.items()
                                if k[0] not in ("do_feed_sbom", "do_feed_builds",
                                                "do_feed_targets")}
                before.tasks = [t for t in before.tasks
                                if t[0] not in ("do_feed_builds", "do_feed_targets")]
                if extra:
                    before.flags[("do_feed_sbom", "depends")] = \
                        " avocado-distro:do_multikernel_merge"
                d = recipe_flags(**feed_values(**extra))
                self.assertEqual(sorted(self.sysroot(d)), sorted(self.sysroot(before)))
                self.assertIn("python3-sbom-cve-check-native", self.sysroot(d))
                self.assertIn("python3-native", self.sysroot(d))
                self.assertFalse({"avocado-distro", "avocado-core", "avocado-stone", "foo",
                                  "linux-yocto"} & set(self.sysroot(d)))


class FeedScheduleTests(unittest.TestCase):
    """What the report run schedules from the modelled feed graph."""

    RECIPES = ("foo", "bar-native", "linux-yocto", "kmod-native", "gcc-cross")

    def setUp(self):
        self.d = recipe_flags(**feed_values())
        self.g = add_recipe(feed_graph(), self.d)
        self.kept = scheduled(self.g)

    def test_every_document_the_feed_links_to_is_a_direct_dependency(self):
        # Restored from sstate only for a task that runs, so each one is.
        sbom = self.g.deps[PN + ":do_feed_sbom"]
        if LINE == "wrynose":
            for pn in self.RECIPES:
                self.assertIn(pn + ":do_create_recipe_spdx", sbom)
            for tid in ("linux-yocto:do_create_spdx", "linux-yocto:do_create_package_spdx",
                        "kmod-native:do_create_spdx"):
                self.assertIn(tid, self.g.deps[PN + ":do_feed_builds"])
        else:
            for pn in self.RECIPES:
                self.assertIn(pn + ":do_create_spdx", sbom)
            for pn in ("foo", "linux-yocto"):
                self.assertIn(pn + ":do_create_package_spdx", sbom)
        # The scanner is no part of the feed.
        self.assertFalse({t for t in self.kept if t.startswith("python3-native:do_create")})

    def test_only_the_kernel_brings_its_build_on_wrynose(self):
        # wrynose's feed document carries the builds of compiled-source
        # kernels only; scarthgap's carries every recipe's build.
        if LINE == "wrynose":
            self.assertNotIn("foo:do_create_spdx", self.kept)
            self.assertNotIn("bar-native:do_create_spdx", self.kept)
            self.assertEqual({t for t in self.kept if t.startswith("foo:")},
                             {"foo:do_create_recipe_spdx"})
        else:
            self.assertFalse([t for t in self.d.tasks if t[0] == "do_feed_builds"])
            self.assertIn("foo:do_compile", self.kept)

    def test_the_targets_own_tasks_are_not_scheduled(self):
        for tid in ("avocado-distro:do_build", "avocado-distro:do_compile",
                    "avocado-distro:do_create_spdx", "avocado-core:do_build",
                    "avocado-stone:do_build", "avocado-stone:do_deploy",
                    "avocado-stone:do_compile", "avocado-stone:do_create_spdx",
                    "foo:do_build", "foo:do_package_write_rpm", "linux-yocto:do_deploy",
                    PN + ":do_feed_targets"):
            self.assertNotIn(tid, self.kept)

    def test_a_meta_target_with_a_build_spdx_task_ships_no_spdx_on_scarthgap(self):
        # On scarthgap the feed asks for every recipe's build SPDX task, and a
        # meta-target's follows its do_compile through the feed and images.
        for pn in ("avocado-distro", "avocado-stone"):
            self.assertEqual(ships_no_spdx(pn), LINE == "scarthgap", pn)

    def test_far_fewer_tasks_than_waiting_for_the_targets_build(self):
        wide = scheduled(add_recipe(feed_graph(), target_build_wiring(
            recipe_flags(**feed_values()))))
        self.assertLess(len(self.kept), len(wide))
        self.assertTrue(self.kept - {PN + ":do_feed_builds"} < wide)


@unittest.skipUnless(oe_meta(), "OE_CORE_LIB not set")
class OeCoreTaskOrderTests(unittest.TestCase):
    """The parts of OE-Core the schedule above relies on."""

    def test_the_recipe_level_spdx_task_waits_only_for_its_own_kind(self):
        text = (oe_meta() / "classes" / "create-spdx-3.0.bbclass").read_text()
        if LINE == "scarthgap":
            self.assertNotIn("do_create_recipe_spdx", text)
            return
        self.assertRegex(text, r"(?m)^addtask do_create_recipe_spdx$")
        self.assertRegex(text,
                         r'(?m)^do_create_recipe_spdx\[deptask\] \+= "do_create_recipe_spdx"$')
        self.assertNotRegex(text, r"(?m)^do_create_recipe_spdx\[(depends|rdeptask)\]")

    def test_the_spdx_tasks_are_sstate_tasks_and_stop_the_sysroot_walk(self):
        text = (oe_meta() / "classes" / "create-spdx-3.0.bbclass").read_text()
        for task in IMAGE_SPDX_TASKS.split():
            self.assertRegex(text, r'(?m)^SSTATETASKS \+= "%s"$' % task)

    def test_a_task_with_a_sysroot_dependency_runs_extend_recipe_sysroot(self):
        text = (oe_meta() / "classes-global" / "staging.bbclass").read_text()
        self.assertIn('if task == "do_configure" or (deps and "populate_sysroot" in deps):',
                      text)


if __name__ == "__main__":
    unittest.main()
