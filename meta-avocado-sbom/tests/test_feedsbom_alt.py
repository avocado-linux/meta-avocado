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


class AltLabelTest(unittest.TestCase):
    def test_label_is_mc_colon_recipe(self):
        self.assertEqual(feedsbom.alt_label("raspberrypi-6_6", "linux-raspberrypi"),
                         "raspberrypi-6_6:linux-raspberrypi")


if __name__ == "__main__":
    unittest.main()
