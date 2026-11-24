#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""Both do_cve_check appends run, whichever order the classes are inherited in.

BitBake keeps a python function's body as text and joins each :append onto it
by string concatenation (data_smart.getVarFlag), then runs the result as one
function. A return in one append's body therefore returns out of the whole
task and silently skips every append spliced after it. These tests build the
spliced body the same way, without bitbake, and run it against a stub datastore.

  python3 -m unittest discover -s meta-avocado-sbom/tests -p 'test_*.py'
"""

import ast
import glob
import json
import os
import re
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
CLASSES = os.path.join(HERE, "..", "classes")
OPTOUT = os.path.join(CLASSES, "avocado-cve-optout.bbclass")
BACKPORTS = os.path.join(CLASSES, "avocado-cve-backports.bbclass")
REPO = os.path.join(HERE, "..", "..")

# BBHandler's patterns: a "python name() {" function runs to a lone "}", and a
# top-level "def" runs while lines are indented, blank or comments.
FUNC_START = re.compile(r"^(?:python\s+)?(?P<func>[\w.\-+{}$:]+)\s*\(\s*\)\s*{$")
DEF_START = re.compile(r"^def\s+(\w+)\(")
DEF_CONT = re.compile(r"(\s+.*)|(^$)|(^#)")

# Stand-in for cve-check.bbclass's own body, which the appends follow.
UPSTREAM = "    d.setVar('UPSTREAM_RAN', '1')\n"


def read_lines(path):
    # BBHandler strips trailing whitespace before matching, so "{ " still
    # opens a function.
    with open(path) as f:
        return [line.rstrip() for line in f.read().splitlines()]


def task_bodies(path, name):
    """(function, body) for every "python <function>() {" in path whose name
    fully matches the regex name, with the body as BBHandler stores it: the
    lines joined with a trailing newline."""
    lines = read_lines(path)
    bodies = []
    i = 0
    while i < len(lines):
        m = FUNC_START.match(lines[i])
        if m and re.fullmatch(name, m.group("func")):
            body = []
            i += 1
            while lines[i] != "}":
                body.append(lines[i])
                i += 1
            bodies.append((m.group("func"), "\n".join(body + [""])))
        i += 1
    return bodies


def defs(path):
    """The class's top-level "def" functions, as source."""
    lines = read_lines(path)
    out = []
    i = 0
    while i < len(lines):
        if DEF_START.match(lines[i]):
            block = [lines[i]]
            i += 1
            while i < len(lines) and DEF_CONT.match(lines[i]):
                block.append(lines[i])
                i += 1
            out.append("\n".join(block) + "\n")
        else:
            i += 1
    return out


def returns_in(body):
    """Return statements at the top level of a function body, not in a nested
    def or lambda, where they would only leave that."""
    tree = ast.parse("def f(d):\n" + body)
    found = []
    stack = list(tree.body[0].body)
    while stack:
        node = stack.pop()
        if isinstance(node, ast.Return):
            found.append(node)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.Lambda, ast.ClassDef)):
            continue
        stack.extend(ast.iter_child_nodes(node))
    return found


class StubData:
    """Just enough of the datastore for the two appends."""

    def __init__(self, values, flags=None):
        self.values = dict(values)
        self.flags = flags or {}

    def getVar(self, name, expand=True):
        return self.values.get(name)

    def setVar(self, name, value):
        self.values[name] = value

    def getVarFlags(self, name):
        return self.flags.get(name)


def stub_bb():
    def remove(path):
        if path and os.path.lexists(path):
            os.unlink(path)

    def mkdirhier(path):
        os.makedirs(path, exist_ok=True)

    bb = types.ModuleType("bb")
    bb.utils = types.SimpleNamespace(remove=remove, mkdirhier=mkdirhier)
    bb.warn = lambda *a: None
    bb.note = lambda *a: None
    return bb


def stub_oe(patch_cves):
    oe = types.ModuleType("oe")
    cve_check = types.ModuleType("oe.cve_check")
    cve_check.get_patched_cves = lambda d: set(patch_cves)
    oe.cve_check = cve_check
    return {"oe": oe, "oe.cve_check": cve_check}


def spliced(order):
    """do_cve_check as bitbake would run it with the classes inherited in
    order: upstream's body, then each class's appends in turn."""
    body = UPSTREAM
    for path in order:
        body += "".join(b for _, b in task_bodies(path, "do_cve_check:append"))
    return "def do_cve_check(d):\n" + body


class CveCheckAppends(unittest.TestCase):
    ORDERS = {
        # kas/feature/cve-check.yml's order.
        "optout-first": (OPTOUT, BACKPORTS),
        "backports-first": (BACKPORTS, OPTOUT),
    }

    def fresh_dir(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)

    def run_task(self, order, pn, cve_product, patch_cves=(), status=None):
        cve_dir = self.dir
        d = StubData(
            {
                "PN": pn,
                "CVE_PRODUCT": cve_product,
                "FILE_DIRNAME": "/layers/meta/recipes-core/%s" % pn,
                "AVOCADO_CVE_OPTOUT_FILE":
                    os.path.join(cve_dir, "%s_optout.json" % pn),
                "AVOCADO_CVE_OPTOUT_VERSION": "1",
                "AVOCADO_CVE_BACKPORTS_FILE":
                    os.path.join(cve_dir, "%s_backports.json" % pn),
                "AVOCADO_CVE_BACKPORTS_VERSION": "1",
                "CVE_CHECK_RECIPE_FILE": os.path.join(cve_dir, "%s_cve" % pn),
                "CVE_CHECK_RECIPE_FILE_JSON":
                    os.path.join(cve_dir, "%s_cve.json" % pn),
            },
            flags={"CVE_STATUS": status or {}},
        )
        scope = {"bb": stub_bb(), "os": os}
        for path in order:
            for src in defs(path):
                exec(compile(src, path, "exec"), scope)
        exec(compile(spliced(order), "do_cve_check", "exec"), scope)
        with mock.patch.dict(sys.modules, stub_oe(patch_cves)):
            scope["do_cve_check"](d)
        return d

    def marker(self, pn, kind):
        path = os.path.join(self.dir, "%s_%s.json" % (pn, kind))
        if not os.path.exists(path):
            return None
        with open(path) as f:
            return json.load(f)

    def touch(self, name, text="{}\n"):
        with open(os.path.join(self.dir, name), "w") as f:
            f.write(text)

    def test_a_scanned_recipe_credits_its_patches(self):
        for label, order in self.ORDERS.items():
            with self.subTest(order=label):
                self.fresh_dir()
                # Left by a build where the recipe still opted out.
                self.touch("busybox_optout.json")
                d = self.run_task(
                    order, "busybox", "busybox",
                    patch_cves={"CVE-2023-42366", "CVE-2022-48174",
                                "CVE-2023-0001"},
                    status={"CVE-2023-0001": "cpe-stable-backport: x"},
                )
                self.assertEqual(d.getVar("UPSTREAM_RAN"), "1")
                self.assertEqual(
                    self.marker("busybox", "backports"),
                    {"version": "1", "name": "busybox",
                     "cves": ["CVE-2022-48174", "CVE-2023-42366"]},
                )
                self.assertIsNone(self.marker("busybox", "optout"))

    def test_an_opted_out_recipe_still_records_why(self):
        for label, order in self.ORDERS.items():
            with self.subTest(order=label):
                self.fresh_dir()
                # Results from a build where the recipe was still scanned.
                self.touch("glibc-locale_cve")
                self.touch("glibc-locale_cve.json")
                self.run_task(order, "glibc-locale", "")
                self.assertEqual(
                    self.marker("glibc-locale", "optout"),
                    {"version": "1", "name": "glibc-locale",
                     "reason": "CVE_PRODUCT is empty"},
                )
                for name in ("glibc-locale_cve", "glibc-locale_cve.json"):
                    self.assertFalse(
                        os.path.exists(os.path.join(self.dir, name)))
                self.assertIsNone(self.marker("glibc-locale", "backports"))

    def test_no_do_cve_check_splice_in_the_tree_returns(self):
        """Every do_cve_check append or prepend anywhere in the tree, including
        override-qualified ones (:prepend:pn-foo, :pn-foo:prepend), so a class
        added later is held to the same rule."""
        patterns = ("**/*.bbclass", "**/*.bb", "**/*.bbappend", "**/*.inc")
        paths = sorted({p for pat in patterns
                        for p in glob.glob(os.path.join(REPO, pat),
                                           recursive=True)})
        seen = 0
        for path in paths:
            splices = task_bodies(
                path, r"do_cve_check(:.+)?:(append|prepend)(:.+)?")
            for name, body in splices:
                seen += 1
                with self.subTest(path=os.path.relpath(path, REPO),
                                  splice=name):
                    self.assertEqual(
                        [r.lineno - 1 for r in returns_in(body)], [])
        # Both classes' appends, at least: a pattern that stopped matching
        # would otherwise pass this vacuously.
        self.assertGreaterEqual(seen, 2)


if __name__ == "__main__":
    unittest.main()
