#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""A wrong statement reference is traced to the multiconfig of its kernel.

Runs avocado-cve-report's own avocado_feed_capture_statements and
avocado_feed_statement_references against stand-in SPDX objects, then
feedsbom.drop_wrong_reference on what they return: a kernel built in two
alternate multiconfigs loses only the build whose statement went wrong.

  cd meta-avocado-sbom/tests && PYTHONPATH=../lib python3 -m unittest discover -p 'test_*.py'
"""

import os
import re
import sys
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

from avocado_sbom import feedsbom  # noqa: E402

REPORT_BB = os.path.join(HERE, "..", "recipes-avocado", "avocado-cve-report",
                         "avocado-cve-report.bb")


class Element:
    def __init__(self, _id):
        self._id = _id
        self.extension = []


class Package(Element):
    def __init__(self, _id, name, version):
        super().__init__(_id)
        self.name = name
        self.software_packageVersion = version


class Statement(Element):
    def __init__(self, _id, to):
        super().__init__(_id)
        self.to = to


class ObjectSet:
    def __init__(self, *objects):
        self.objects = list(objects)

    def foreach_type(self, typ):
        return [o for o in self.objects if isinstance(o, typ)]

    def find_by_id(self, _id):
        for o in self.objects:
            if o._id == _id:
                return o
        return None


def recipe_functions():
    with open(REPORT_BB) as f:
        text = f.read() + "\n#"
    spdx30 = types.SimpleNamespace(Element=Element, software_Package=Package,
                                   security_VulnAssessmentRelationship=Statement)
    sbom30 = types.SimpleNamespace(get_alias=lambda e: None)
    oe = types.ModuleType("oe")
    oe.spdx30, oe.sbom30 = spdx30, sbom30
    saved = {k: sys.modules.get(k) for k in ("oe", "oe.spdx30", "oe.sbom30")}
    sys.modules.update({"oe": oe, "oe.spdx30": spdx30, "oe.sbom30": sbom30})
    ns = {}
    for name in ("avocado_feed_rid", "avocado_feed_alias",
                 "avocado_feed_capture_statements", "avocado_feed_statement_references"):
        m = re.search(r"^(def %s\(.*?)(?=^\S)" % name, text, re.M | re.S)
        assert m, "%s is gone from the recipe" % name
        exec(m.group(1), ns)
    return ns, saved


class StatementReferenceTest(unittest.TestCase):
    def setUp(self):
        self.ns, saved = recipe_functions()

        def restore():
            for k, v in saved.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v
        self.addCleanup(restore)

    def test_only_the_multiconfig_whose_statement_went_wrong_is_dropped(self):
        default = Package("pkg-default", "linux", "6.12")
        good = Package("pkg-good", "linux", "6.6")
        bad = Package("pkg-bad", "linux", "6.1")
        docs = [ObjectSet(default, Statement("vex-default", ["pkg-default"])),
                ObjectSet(good, Statement("vex-good", ["pkg-good"])),
                ObjectSet(bad, Statement("vex-bad", ["pkg-bad"]))]
        captured = self.ns["avocado_feed_capture_statements"](
            docs, {"linux"}, {"pkg-good": "good-mc", "pkg-bad": "bad-mc"})
        self.assertEqual(sorted((c[0], c[2]) for c in captured),
                         [("vex-bad", "bad-mc"), ("vex-default", ""), ("vex-good", "good-mc")])
        # Assembled, the bad kernel's statement now points at the default's
        # package.
        assembled = ObjectSet(default, good, bad,
                              Statement("vex-default", ["pkg-default"]),
                              Statement("vex-good", ["pkg-good"]),
                              Statement("vex-bad", ["pkg-default"]))
        wrong = feedsbom.wrong_kernel_references(
            self.ns["avocado_feed_statement_references"](assembled, captured))
        self.assertEqual([(w["mc"], w["kernel_version"], w["target_version"]) for w in wrong],
                         [("bad-mc", "6.1", "6.12")])
        kept, not_covered = feedsbom.drop_wrong_reference(
            [("good-mc", "linux", ["hg"]), ("bad-mc", "linux", ["hb"])], wrong)
        self.assertEqual(kept, [("good-mc", "linux", ["hg"])])
        self.assertEqual([n["mc"] for n in not_covered], ["bad-mc"])

    def test_a_default_statement_gone_wrong_drops_every_alternate(self):
        default = Package("pkg-default", "linux", "6.12")
        good = Package("pkg-good", "linux", "6.6")
        captured = self.ns["avocado_feed_capture_statements"](
            [ObjectSet(default, Statement("vex-default", ["pkg-default"]))],
            {"linux"}, {"pkg-good": "good-mc"})
        assembled = ObjectSet(default, good, Statement("vex-default", ["pkg-good"]))
        wrong = feedsbom.wrong_kernel_references(
            self.ns["avocado_feed_statement_references"](assembled, captured))
        self.assertEqual([w["mc"] for w in wrong], [""])
        kept, _not_covered = feedsbom.drop_wrong_reference(
            [("good-mc", "linux", ["hg"])], wrong)
        self.assertEqual(kept, [])


if __name__ == "__main__":
    unittest.main()
