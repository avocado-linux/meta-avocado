#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""The alternate-kernel planning logic names its pairs, directories and clashes.

Everything here is pure logic over plain values, so the suite needs no build.

  python3 -m unittest discover -s meta-avocado-sbom/tests -p 'test_*.py'
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

from avocado_sbom import feedsbom  # noqa: E402


class ParseAltRecipesTest(unittest.TestCase):
    def test_pairs_in_order(self):
        text = "raspberrypi-6_6:linux-raspberrypi raspberrypi-6_6:cryptsetup other:bar"
        self.assertEqual(
            feedsbom.parse_alt_recipes(text),
            (
                [
                    ("raspberrypi-6_6", "linux-raspberrypi"),
                    ("raspberrypi-6_6", "cryptsetup"),
                    ("other", "bar"),
                ],
                [],
            ),
        )

    def test_duplicates_collapse_keeping_first_order(self):
        self.assertEqual(
            feedsbom.parse_alt_recipes("a:x b:y a:x"), ([("a", "x"), ("b", "y")], [])
        )

    def test_malformed_entries_are_reported_not_paired(self):
        pairs, malformed = feedsbom.parse_alt_recipes("mc: :recipe mc good:one")
        self.assertEqual(pairs, [("good", "one")])
        self.assertEqual(malformed, ["mc:", ":recipe", "mc"])

    def test_empty_and_whitespace_only(self):
        self.assertEqual(feedsbom.parse_alt_recipes(""), ([], []))
        self.assertEqual(feedsbom.parse_alt_recipes("  \n\t "), ([], []))

    def test_any_whitespace_separates(self):
        pairs, _ = feedsbom.parse_alt_recipes("a:x\n  b:y\tc:z")
        self.assertEqual(pairs, [("a", "x"), ("b", "y"), ("c", "z")])


class AltTmpdirTest(unittest.TestCase):
    def test_tmpdir_is_topdir_tmp_multiconfig(self):
        self.assertEqual(
            feedsbom.alt_tmpdir("/work/build", "raspberrypi-6_6"),
            "/work/build/tmp-raspberrypi-6_6",
        )


class ClassifyAltTest(unittest.TestCase):
    def test_splits_included_and_not_covered(self):
        docs = {("mc", "has"): ["h1", "h2"]}
        pairs = [("mc", "has"), ("mc", "lacks")]
        included, not_covered = feedsbom.classify_alt(
            pairs, lambda mc, recipe: docs.get((mc, recipe), [])
        )
        self.assertEqual(included, [("mc", "has", ["h1", "h2"])])
        self.assertEqual(len(not_covered), 1)
        entry = not_covered[0]
        self.assertEqual((entry["mc"], entry["recipe"]), ("mc", "lacks"))
        self.assertIn("no document in tmp-mc/deploy/spdx", entry["reason"])

    def test_empty_pairs(self):
        self.assertEqual(feedsbom.classify_alt([], lambda mc, r: ["x"]), ([], []))


class WrongKernelReferencesTest(unittest.TestCase):
    def test_returns_only_mismatches(self):
        ok = {"kernel_version": "6.6", "target_version": "6.6"}
        bad = {"kernel_version": "6.6", "target_version": "6.12"}
        self.assertEqual(feedsbom.wrong_kernel_references([ok, bad, ok]), [bad])

    def test_empty_when_all_match_or_no_statements(self):
        ok = {"kernel_version": "6.6", "target_version": "6.6"}
        self.assertEqual(feedsbom.wrong_kernel_references([ok]), [])
        self.assertEqual(feedsbom.wrong_kernel_references([]), [])


class AliasCollisionsTest(unittest.TestCase):
    def test_sorted_shared_aliases(self):
        self.assertEqual(
            feedsbom.alias_collisions(
                ["pkg-linux", "static", "only-default"], iter(["static", "pkg-linux", "x"])
            ),
            ["pkg-linux", "static"],
        )

    def test_none_shared(self):
        self.assertEqual(feedsbom.alias_collisions(["a"], ["b"]), [])
        self.assertEqual(feedsbom.alias_collisions([], []), [])

    def test_duplicates_within_one_side_report_once(self):
        self.assertEqual(feedsbom.alias_collisions(["a", "a"], ["a", "a"]), ["a"])


class ReferencedAliasesTest(unittest.TestCase):
    def test_only_shared_aliases_that_something_targets(self):
        self.assertEqual(
            feedsbom.referenced_aliases(
                ["urn:b", "urn:a", "urn:c"], iter(["urn:c", "urn:x", "urn:a", "urn:c"])
            ),
            ["urn:a", "urn:c"],
        )

    def test_nothing_shared_or_nothing_targeted(self):
        self.assertEqual(feedsbom.referenced_aliases([], ["urn:a"]), [])
        self.assertEqual(feedsbom.referenced_aliases(["urn:a"], []), [])


class DropAliasCollidedTest(unittest.TestCase):
    INCLUDED = [("mc", "kern", ["h"]), ("mc", "other", ["h2"])]

    def test_kernel_with_referenced_shared_alias_is_not_covered(self):
        kept, not_covered = feedsbom.drop_alias_collided(
            self.INCLUDED, {"mc:kern": ["urn:a", "urn:b"]}, ["urn:b", "urn:zzz"]
        )
        self.assertEqual(kept, [("mc", "other", ["h2"])])
        self.assertEqual(len(not_covered), 1)
        self.assertEqual((not_covered[0]["mc"], not_covered[0]["recipe"]), ("mc", "kern"))
        self.assertEqual(not_covered[0]["reason"], "alias collision: urn:b")

    def test_every_referenced_alias_is_named_in_sorted_order(self):
        kept, not_covered = feedsbom.drop_alias_collided(
            self.INCLUDED, {"mc:kern": ["urn:c", "urn:a", "urn:b"]}, ["urn:b", "urn:a"]
        )
        self.assertEqual([n["reason"] for n in not_covered], ["alias collision: urn:a, urn:b"])

    def test_shared_but_unreferenced_aliases_keep_the_kernel(self):
        kept, not_covered = feedsbom.drop_alias_collided(
            self.INCLUDED, {"mc:kern": ["urn:a"]}, ["urn:other"]
        )
        self.assertEqual(kept, self.INCLUDED)
        self.assertEqual(not_covered, [])

    def test_referenced_alias_of_another_recipe_does_not_count(self):
        kept, not_covered = feedsbom.drop_alias_collided(
            self.INCLUDED, {"mc:other": ["urn:a"]}, ["urn:a"]
        )
        self.assertEqual([k[1] for k in kept], ["kern"])
        self.assertEqual([n["recipe"] for n in not_covered], ["other"])

    def test_same_recipe_in_two_multiconfigs_is_judged_per_multiconfig(self):
        included = [("mcA", "kern", ["hA"]), ("mcB", "kern", ["hB"])]
        kept, not_covered = feedsbom.drop_alias_collided(
            included, {"mcA:kern": ["urn:a"], "mcB:kern": []}, ["urn:a"]
        )
        self.assertEqual(kept, [("mcB", "kern", ["hB"])])
        self.assertEqual([(n["mc"], n["recipe"]) for n in not_covered], [("mcA", "kern")])


class DropWrongReferenceTest(unittest.TestCase):
    INCLUDED = [("mc", "kern", ["h"]), ("mc", "other", ["h2"])]

    def test_recipe_named_by_a_wrong_statement_is_not_covered(self):
        wrong = [
            {"recipe": "kern", "kernel_version": "6.6", "target_version": "6.12"},
            {"recipe": "kern", "kernel_version": "6.6", "target_version": None},
        ]
        kept, not_covered = feedsbom.drop_wrong_reference(self.INCLUDED, wrong)
        self.assertEqual(kept, [("mc", "other", ["h2"])])
        self.assertEqual(len(not_covered), 1)
        self.assertEqual(not_covered[0]["recipe"], "kern")
        self.assertEqual(
            not_covered[0]["reason"],
            "reference collision: 2 statement(s) target another version",
        )

    def test_no_wrong_statements_keeps_everything(self):
        self.assertEqual(
            feedsbom.drop_wrong_reference(self.INCLUDED, []), (self.INCLUDED, [])
        )

    def test_a_reference_traced_to_one_multiconfig_drops_that_build_only(self):
        included = [("good-mc", "linux", ["hg"]), ("bad-mc", "linux", ["hb"])]
        wrong = [{"mc": "bad-mc", "recipe": "linux",
                  "kernel_version": "6.1", "target_version": "6.12"}]
        kept, not_covered = feedsbom.drop_wrong_reference(included, wrong)
        self.assertEqual(kept, [("good-mc", "linux", ["hg"])])
        self.assertEqual([(n["mc"], n["recipe"], n["reason"]) for n in not_covered],
                         [("bad-mc", "linux",
                           "reference collision: 1 statement(s) target another version")])

    def test_a_reference_traced_to_none_drops_every_build_of_the_recipe(self):
        included = [("good-mc", "linux", ["hg"]), ("bad-mc", "linux", ["hb"]),
                    ("good-mc", "other", ["ho"])]
        for wrong in ([{"mc": "", "recipe": "linux", "kernel_version": "6.12",
                        "target_version": "6.1"}],
                      [{"recipe": "linux", "kernel_version": "6.12",
                        "target_version": "6.1"}]):
            with self.subTest(wrong=wrong):
                kept, not_covered = feedsbom.drop_wrong_reference(included, wrong)
                self.assertEqual(kept, [("good-mc", "other", ["ho"])])
                self.assertEqual(sorted(n["mc"] for n in not_covered),
                                 ["bad-mc", "good-mc"])

    def test_the_count_adds_the_untraced_references(self):
        included = [("bad-mc", "linux", ["hb"])]
        wrong = [{"mc": "bad-mc", "recipe": "linux", "kernel_version": "6.1",
                  "target_version": "6.12"},
                 {"mc": "", "recipe": "linux", "kernel_version": "6.12",
                  "target_version": "6.1"},
                 {"mc": "other-mc", "recipe": "linux", "kernel_version": "6.6",
                  "target_version": None}]
        _kept, not_covered = feedsbom.drop_wrong_reference(included, wrong)
        self.assertEqual(not_covered[0]["reason"],
                         "reference collision: 2 statement(s) target another version")


def build(products, versions, statements=()):
    return {"products": set(products), "versions": set(versions),
            "statements": set(statements)}


STOCK = build(["linux_kernel"], ["6.18.52", "6.18.52+git"],
              [("CVE-1", "VexFixed", "fixed-version", "", "")])


class VexOverlapTest(unittest.TestCase):
    def test_shared_product_and_version_with_other_statements(self):
        rt = build(["linux_kernel"], ["6.18.52", "6.18.52+git"])
        self.assertEqual(feedsbom.vex_overlap(rt, STOCK),
                         ("linux_kernel", "6.18.52", "CVE-1"))

    def test_the_same_statements_cannot_change_a_result(self):
        rt = build(["linux_kernel"], ["6.18.52"], STOCK["statements"])
        self.assertIsNone(feedsbom.vex_overlap(rt, STOCK))

    def test_another_version_does_not_overlap(self):
        other = build(["linux_kernel"], ["6.18.53", "6.18.53+git"])
        self.assertIsNone(feedsbom.vex_overlap(other, STOCK))

    def test_another_product_at_the_same_version_overlaps(self):
        # A record can name both products, and the scanner aliases products,
        # so a shared version alone is enough.
        for other in (build(["busybox"], ["6.18.52"]), build([], ["6.18.52"])):
            with self.subTest(other=other):
                self.assertEqual(feedsbom.vex_overlap(other, STOCK), (None, "6.18.52", "CVE-1"))

    def test_statements_are_compared_one_cve_at_a_time(self):
        # The same statement about CVE-1, and one about CVE-2 the stock kernel
        # lacks: CVE-2 is the one named.
        rt = build(["linux_kernel"], ["6.18.52"],
                   list(STOCK["statements"]) + [("CVE-2", "VexFixed", "backported-patch",
                                                 "", "")])
        self.assertEqual(feedsbom.vex_overlap(rt, STOCK),
                         ("linux_kernel", "6.18.52", "CVE-2"))

    def test_any_statement_field_counts(self):
        for statement in (("CVE-1", "VexNotAffected", "fixed-version", "", ""),
                          ("CVE-1", "VexFixed", "backported-patch", "", ""),
                          ("CVE-1", "VexFixed", "fixed-version", "x", ""),
                          ("CVE-2", "VexFixed", "fixed-version", "", "")):
            with self.subTest(statement=statement):
                rt = build(["linux_kernel"], ["6.18.52"], [statement])
                self.assertIsNotNone(feedsbom.vex_overlap(rt, STOCK))


class VexTwinTest(unittest.TestCase):
    def test_a_default_build_with_the_same_products_versions_and_statements(self):
        twin = build(["linux_kernel"], ["6.18.52", "6.18.52+git"], STOCK["statements"])
        self.assertTrue(feedsbom.vex_twin(twin, {"x": build(["x"], ["1"]), "y": twin}))

    def test_another_cpe_or_package_version_is_no_twin(self):
        # One product and version set, but the scanner matches vendor and
        # part, and the package version before any CPE.
        def full(cpe, package_version):
            return dict(build(["edk2"], ["39.2.1+git", "202505"]), cpes={cpe},
                        package_version=package_version)
        default = full("cpe:2.3:a:tianocore:edk2:202505:*:*:*:*:*:*:*", "39.2.1+git")
        self.assertTrue(feedsbom.vex_twin(dict(default), {"edk2": default}))
        for other in (full("cpe:2.3:a:*:edk2:202505:*:*:*:*:*:*:*", "39.2.1+git"),
                      full("cpe:2.3:o:tianocore:edk2:202505:*:*:*:*:*:*:*", "39.2.1+git"),
                      full("cpe:2.3:a:tianocore:edk2:202505:*:*:*:*:*:*:*", "202505")):
            with self.subTest(other=other):
                self.assertFalse(feedsbom.vex_twin(other, {"edk2": default}))

    def test_any_difference_is_no_twin(self):
        base = (["jetson_linux"], ["39.2.1"], [("CVE-1", "VexFixed", "", "", "")])
        for changed in ((["edk2"], base[1], base[2]), (base[0], ["39.2.0"], base[2]),
                        (base[0], base[1], [])):
            with self.subTest(changed=changed):
                self.assertFalse(feedsbom.vex_twin(build(*changed), {"oot": build(*base)}))


EDK2 = build(["edk2"], ["39.2.1+git", "202505"], [("CVE-1", "VexFixed", "fixed-version", "", "")])
OOT = build(["jetson_linux"], ["39.2.1", "39.2.1+git"])
JETSON_ALTS = [(mc, "nvidia-kernel-oot", [mc]) for mc in ("jetson-l4t", "jetson-rt", "jetson-l4t-rt")]


class DropVexOverlapTest(unittest.TestCase):
    def test_an_alternate_with_other_statements_is_not_covered(self):
        included = [("jetson-rt", "linux-yocto-rt", ["h"]), ("jetson-l4t", "linux-l4t", ["h2"])]
        alt = {"jetson-rt:linux-yocto-rt": build(["linux_kernel"], ["6.18.52"]),
               "jetson-l4t:linux-l4t": build(["linux_kernel"], ["6.8.12"])}
        kept, not_covered = feedsbom.drop_vex_overlap(included, alt, {"linux-yocto": STOCK})
        self.assertEqual(kept, [("jetson-l4t", "linux-l4t", ["h2"])])
        self.assertEqual(not_covered, [{
            "mc": "jetson-rt", "recipe": "linux-yocto-rt",
            "reason": "VEX overlap: linux_kernel 6.18.52 is also linux-yocto, with other "
                      "statements on CVE-1"}])

    def test_another_product_names_the_version_and_the_cve(self):
        kept, not_covered = feedsbom.drop_vex_overlap(
            [("mc", "oot", ["h"])], {"mc:oot": build(["oot"], ["6.18.52"])},
            {"linux-yocto": STOCK})
        self.assertEqual(kept, [])
        self.assertEqual(not_covered[0]["reason"],
                         "VEX overlap: 6.18.52 is also linux-yocto, with other statements "
                         "on CVE-1")

    def test_of_two_overlapping_alternates_the_first_stays(self):
        included = [("a", "k1", ["h1"]), ("b", "k2", ["h2"])]
        alt = {"a:k1": build(["linux_kernel"], ["6.8.12"], [("CVE-9", "VexFixed", "", "", "")]),
               "b:k2": build(["linux_kernel"], ["6.8.12"])}
        kept, not_covered = feedsbom.drop_vex_overlap(included, alt, {"linux-yocto": STOCK})
        self.assertEqual(kept, [("a", "k1", ["h1"])])
        self.assertEqual(not_covered[0]["reason"],
                         "VEX overlap: linux_kernel 6.8.12 is also a:k1, with other statements "
                         "on CVE-9")

    def test_a_dropped_alternate_is_not_compared_with(self):
        # k1 overlaps the default and goes; k2 overlaps only k1, so it stays.
        included = [("a", "k1", ["h1"]), ("b", "k2", ["h2"])]
        alt = {"a:k1": build(["linux_kernel"], ["6.18.52", "6.8.12"]),
               "b:k2": build(["linux_kernel"], ["6.8.12"], [("CVE-9", "VexFixed", "", "", "")])}
        kept, not_covered = feedsbom.drop_vex_overlap(included, alt, {"linux-yocto": STOCK})
        self.assertEqual(kept, [("b", "k2", ["h2"])])
        self.assertEqual([n["recipe"] for n in not_covered], ["k1"])

    def test_an_alternate_without_a_build_is_kept(self):
        included = [("a", "k1", ["h1"])]
        self.assertEqual(feedsbom.drop_vex_overlap(included, {}, {"linux-yocto": STOCK}),
                         (included, []))

    def test_every_twin_of_a_default_module_recipe_stays_beside_firmware_of_its_version(self):
        # Jetson: the default multiconfig's nvidia-kernel-oot and
        # edk2-firmware-tegra share version 39.2.1, and three alternate
        # multiconfigs build nvidia-kernel-oot again with the same statements.
        alt = {feedsbom.alt_label(mc, r): build(["jetson_linux"], ["39.2.1", "39.2.1+git"])
               for mc, r, _h in JETSON_ALTS}
        defaults = {"edk2-firmware-tegra": EDK2, "nvidia-kernel-oot": OOT}
        self.assertEqual(feedsbom.drop_vex_overlap(JETSON_ALTS, alt, defaults), (JETSON_ALTS, []))
        # Without its twin in the default multiconfig, the version it shares
        # with the firmware is an overlap.
        kept, not_covered = feedsbom.drop_vex_overlap(
            JETSON_ALTS[:1], alt, {"edk2-firmware-tegra": EDK2})
        self.assertEqual(kept, [])
        self.assertEqual(not_covered[0]["reason"],
                         "VEX overlap: 39.2.1+git is also edk2-firmware-tegra, with other "
                         "statements on CVE-1")

    def test_an_alternate_with_a_statement_its_default_twin_lacks_is_not_covered(self):
        alt = {feedsbom.alt_label(mc, r): build(["jetson_linux"], ["39.2.1", "39.2.1+git"])
               for mc, r, _h in JETSON_ALTS}
        alt["jetson-rt:nvidia-kernel-oot"] = build(
            ["jetson_linux"], ["39.2.1", "39.2.1+git"],
            [("CVE-3", "VexNotAffected", "cpe-incorrect", "", "")])
        kept, not_covered = feedsbom.drop_vex_overlap(
            JETSON_ALTS, alt, {"edk2-firmware-tegra": EDK2, "nvidia-kernel-oot": OOT})
        self.assertEqual([mc for mc, _r, _h in kept], ["jetson-l4t", "jetson-l4t-rt"])
        self.assertEqual(not_covered, [{
            "mc": "jetson-rt", "recipe": "nvidia-kernel-oot",
            "reason": "VEX overlap: 39.2.1+git is also edk2-firmware-tegra, with other "
                      "statements on CVE-1"}])


class DropUnresolvedTest(unittest.TestCase):
    def test_an_alternate_whose_own_link_is_unresolved_is_not_covered(self):
        included = [("jetson-rt", "linux-yocto-rt", ["h"]), ("jetson-l4t", "linux-l4t", ["h2"])]
        needs = {"jetson-rt:linux-yocto-rt": {"alias/a", "alias/b", "alias/c"},
                 "jetson-l4t:linux-l4t": {"alias/c"}}
        kept, not_covered = feedsbom.drop_unresolved(included, needs, ["alias/a", "alias/b"])
        self.assertEqual(kept, [("jetson-l4t", "linux-l4t", ["h2"])])
        self.assertEqual(not_covered, [{"mc": "jetson-rt", "recipe": "linux-yocto-rt",
                                        "reason": "unresolved reference: 2 identifier(s)"}])

    def test_nothing_unresolved_keeps_everything(self):
        included = [("a", "k", ["h"])]
        self.assertEqual(feedsbom.drop_unresolved(included, {"a:k": {"x"}}, set()),
                         (included, []))


class AltLabelTest(unittest.TestCase):
    def test_label_is_mc_colon_recipe(self):
        self.assertEqual(feedsbom.alt_label("raspberrypi-6_6", "linux-raspberrypi"),
                         "raspberrypi-6_6:linux-raspberrypi")


if __name__ == "__main__":
    unittest.main()
