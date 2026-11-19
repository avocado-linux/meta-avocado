# SPDX-License-Identifier: Apache-2.0
"""avocado-kernel-feed.bbclass: which kernels the debug-info switch changes.

Every Avocado kernel inherits the class, so its anonymous python decides
which of them AVOCADO_KERNEL_DEBUGINFO rebuilds: linux-yocto and
linux-yocto-dev only, not under module-signing, with the runtime-off feature
only where a machine opts in. Runs that python against a fake datastore.

Run with:
    PYTHONPATH=meta-avocado/lib python3 -m unittest discover -s meta-avocado/tests
"""

import re
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LAYER = ROOT / "meta-avocado"
CLASS = LAYER / "classes" / "avocado-kernel-feed.bbclass"
DEBUG = " features/debug/debug-kernel.scc"
RUNTIME_OFF = " avocado/debug-kernel-runtime-off.scc"
KMETA = " file://avocado-kmeta;type=kmeta;destsuffix=avocado-kmeta"
SWITCHED = ("linux-yocto", "linux-yocto-dev")


def _anonymous():
    m = re.search(r"^python __anonymous\(\) \{\n(.*?)^\}", CLASS.read_text(), re.M | re.S)
    assert m, "the class's anonymous python is gone"
    ns = {}
    exec("def anonymous(d, bb):\n" + textwrap.indent(textwrap.dedent(m.group(1)), "    "), ns)
    return ns["anonymous"]


def _defaults():
    return dict(re.findall(r'^(\w+) \?\?= "([^"]*)"', CLASS.read_text(), re.M))


def _inherits(path, layer):
    text = path.read_text()
    if re.search(r"(?m)^inherit .*\bavocado-kernel-feed\b", text):
        return True
    # Several families inherit it from an .inc their bbappends require.
    return any(_inherits(layer / inc, layer)
               for inc in re.findall(r"(?m)^require (\S+)$", text) if (layer / inc).is_file())


def _inheritors():
    """PN of every kernel recipe the layers append the class to."""
    pns = set()
    for path in ROOT.glob("meta-*/**/*.bbappend"):
        if _inherits(path, ROOT / path.relative_to(ROOT).parts[0]):
            pns.add(re.sub(r"_[^_]*$", "", path.stem))
    return pns


class Datastore:
    def __init__(self, values):
        self.vars = dict(values)

    def getVar(self, name):
        return self.vars.get(name)

    def setVar(self, name, value):
        self.vars[name] = value

    def appendVar(self, name, value):
        self.vars[name] = (self.vars.get(name) or "") + value

    def prependVar(self, name, value):
        self.vars[name] = value + (self.vars.get(name) or "")


class Bb:
    class utils:
        @staticmethod
        def contains(var, item, truevalue, falsevalue, d):
            return truevalue if item in (d.getVar(var) or "").split() else falsevalue


class DebugInfoGating(unittest.TestCase):
    def run_class(self, pn, switch="1", features="systemd", runtime_off=None):
        values = dict(_defaults())
        values.update({
            "PN": pn,
            "DISTRO_FEATURES": features,
            "KERNEL_FEATURES": "cfg/x.scc",
            "SRC_URI": "git://kernel",
            "FILESEXTRAPATHS": "/bsp/files:",
            "AVOCADO_LAYER_DIR": "/layers/meta-avocado",
            "SPDX_INCLUDE_COMPILED_SOURCES:pn-" + pn: "1",
            "SPDX_INCLUDE_SOURCES:pn-" + pn: "1",
        })
        if switch is not None:
            values["AVOCADO_KERNEL_DEBUGINFO"] = switch
        if runtime_off is not None:
            values["AVOCADO_KERNEL_DEBUGINFO_RUNTIME_OFF"] = runtime_off
        d = Datastore(values)
        _anonymous()(d, Bb)
        return values, d.vars

    def assertUnchanged(self, **kw):
        before, after = self.run_class(**kw)
        self.assertEqual(after, before)

    def test_switched_kernels_get_debug_info(self):
        for pn in SWITCHED:
            with self.subTest(pn=pn):
                before, after = self.run_class(pn)
                self.assertEqual(after["KERNEL_FEATURES"], "cfg/x.scc" + DEBUG)
                # Only KERNEL_FEATURES moves; the SPDX switches stay on.
                del after["KERNEL_FEATURES"], before["KERNEL_FEATURES"]
                self.assertEqual(after, before)

    def test_off_by_default(self):
        self.assertEqual(_defaults()["AVOCADO_KERNEL_DEBUGINFO"], "0")
        for pn in SWITCHED:
            for switch in (None, "0"):
                for features in ("systemd", "systemd module-signing"):
                    with self.subTest(pn=pn, switch=switch, features=features):
                        self.assertUnchanged(pn=pn, switch=switch, features=features,
                                             runtime_off="1")

    def test_other_kernels_inheriting_the_class_are_untouched(self):
        others = _inheritors() - set(SWITCHED)
        # Guards the discovery below: a short set would pass vacuously.
        for pn in ("linux-raspberrypi", "linux-yocto-rt", "linux-qcom",
                    "linux-noble-nvidia-tegra", "linux-imx"):
            self.assertIn(pn, others)
        for pn in sorted(others):
            with self.subTest(pn=pn):
                self.assertUnchanged(pn=pn, runtime_off="1")

    def test_module_signing_keeps_the_kernel_and_drops_the_source_lists(self):
        for pn in SWITCHED:
            with self.subTest(pn=pn):
                before, after = self.run_class(pn, features="systemd module-signing",
                                               runtime_off="1")
                self.assertEqual(after["SPDX_INCLUDE_COMPILED_SOURCES:pn-" + pn], "0")
                self.assertEqual(after["SPDX_INCLUDE_SOURCES:pn-" + pn], "0")
                for name in ("KERNEL_FEATURES", "SRC_URI", "FILESEXTRAPATHS"):
                    self.assertEqual(after[name], before[name], name)

    def test_runtime_off_only_where_a_machine_opts_in(self):
        self.assertEqual(_defaults()["AVOCADO_KERNEL_DEBUGINFO_RUNTIME_OFF"], "0")
        for pn in SWITCHED:
            for runtime_off in (None, "0"):
                with self.subTest(pn=pn, runtime_off=runtime_off):
                    _, after = self.run_class(pn, runtime_off=runtime_off)
                    self.assertNotIn(RUNTIME_OFF, after["KERNEL_FEATURES"])
                    self.assertNotIn("avocado-kmeta", after["SRC_URI"])
                    self.assertEqual(after["FILESEXTRAPATHS"], "/bsp/files:")

    def test_runtime_off_follows_the_debug_feature(self):
        for pn in SWITCHED:
            with self.subTest(pn=pn):
                _, after = self.run_class(pn, runtime_off="1")
                # Last, so merge_config.sh lets it win over the BSP's fragments.
                self.assertEqual(after["KERNEL_FEATURES"], "cfg/x.scc" + DEBUG + RUNTIME_OFF)
                self.assertEqual(after["SRC_URI"], "git://kernel" + KMETA)
                self.assertEqual(after["FILESEXTRAPATHS"],
                                 "/layers/meta-avocado/files:/bsp/files:")

    def test_the_runtime_off_feature_is_where_the_class_points(self):
        scc = LAYER / "files" / "avocado-kmeta" / RUNTIME_OFF.strip()
        self.assertTrue(scc.is_file(), scc)
        m = re.search(r"(?m)^kconf \S+ (\S+)$", scc.read_text())
        self.assertIsNotNone(m)
        self.assertTrue((scc.parent / m.group(1)).is_file(), m.group(1))

    def test_opt_ins_are_per_machine(self):
        # A bare assignment would turn the off-list on for every machine the
        # recipe builds for, including ones where DEBUG_KERNEL is already on.
        opt_ins = []
        for path in ROOT.glob("meta-*/**/*.bb*"):
            if path.is_relative_to(LAYER / "classes"):
                continue
            for line in path.read_text().splitlines():
                m = re.match(r"\s*AVOCADO_KERNEL_DEBUGINFO_RUNTIME_OFF(\S*)\s*\S*=", line)
                if m:
                    opt_ins.append((path.name, m.group(1)))
        self.assertTrue(opt_ins)
        for name, override in opt_ins:
            with self.subTest(file=name):
                self.assertRegex(override, r"^:avocado-\S+$")

    def test_the_qemu_machines_opt_in(self):
        # DEBUG_KERNEL is off on both, so the switch alone would turn on the
        # runtime debug options their BSP requests.
        text = (ROOT / "meta-avocado-qemu" / "recipes-kernel" / "linux"
                / "linux-yocto_%.bbappend").read_text()
        for machine in ("avocado-qemux86-64", "avocado-qemuarm64"):
            with self.subTest(machine=machine):
                self.assertRegex(text, r'(?m)^AVOCADO_KERNEL_DEBUGINFO_RUNTIME_OFF:%s = "1"$'
                                 % re.escape(machine))


if __name__ == "__main__":
    unittest.main()
