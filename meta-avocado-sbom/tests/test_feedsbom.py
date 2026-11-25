#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""The feed scan selects recipes, gates on missing documents and states its scope.

Everything here is pure logic over plain values, so the suite needs no build.

  python3 -m unittest discover -s meta-avocado-sbom/tests -p 'test_*.py'
"""

import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

from avocado_sbom import feedsbom  # noqa: E402


class FeedRecipesTest(unittest.TestCase):
    def test_distinct_sorted_recipes_from_many_packages(self):
        packages = {
            "big-%d" % i: {"recipe": "big", "version": "1", "origin": "pkgdata"}
            for i in range(40)
        }
        packages["small"] = {"recipe": "small", "version": "2", "origin": "pkgdata"}
        self.assertEqual(feedsbom.feed_recipes(packages), ["big", "small"])

    def test_empty_mapping(self):
        self.assertEqual(feedsbom.feed_recipes({}), [])


class ClassifyTest(unittest.TestCase):
    def test_roots_in_recipe_order_and_missing_sorted(self):
        found = {"b": ["h1", "h2"], "a": [], "d": [], "c": ["h3"]}
        roots, missing = feedsbom.classify(["b", "a", "d", "c"], found.__getitem__)
        self.assertEqual(roots, [("b", "h1"), ("b", "h2"), ("c", "h3")])
        self.assertEqual(missing, ["a", "d"])

    def test_missing_is_sorted_not_input_order(self):
        roots, missing = feedsbom.classify(["z", "m"], lambda r: [])
        self.assertEqual(roots, [])
        self.assertEqual(missing, ["m", "z"])

    def test_empty_recipes(self):
        self.assertEqual(feedsbom.classify([], lambda r: ["x"]), ([], []))


class CheckMissingTest(unittest.TestCase):
    def test_over_ceiling_names_every_recipe(self):
        with self.assertRaises(feedsbom.FeedSbomError) as ctx:
            feedsbom.check_missing(["rec-a", "rec-b", "rec-c"], 2)
        self.assertTrue(
            str(ctx.exception).endswith(": rec-a, rec-b, rec-c"), str(ctx.exception)
        )

    def test_at_ceiling_passes(self):
        self.assertIsNone(feedsbom.check_missing(["a", "b"], 2))

    def test_none_missing_with_zero_ceiling(self):
        self.assertIsNone(feedsbom.check_missing([], 0))

    def test_one_over_zero_ceiling_fails(self):
        with self.assertRaises(feedsbom.FeedSbomError):
            feedsbom.check_missing(["a"], 0)


class CoverageSummaryTest(unittest.TestCase):
    def test_exact_shape(self):
        roots = [("a", "h1"), ("b", "h2")]
        summary = feedsbom.coverage_summary(roots, ["y", "x"], 7)
        self.assertEqual(
            summary,
            {
                "roots": 2,
                "no_document": ["x", "y"],
                "unresolved_ids": 7,
                "alt_included": [],
                "alt_not_covered": [],
            },
        )

    def test_alt_lists_carried(self):
        summary = feedsbom.coverage_summary(
            [], [], 0, alt_included=("p",), alt_not_covered=("q",)
        )
        self.assertEqual(summary["alt_included"], ["p"])
        self.assertEqual(summary["alt_not_covered"], ["q"])
        self.assertEqual(
            sorted(summary),
            ["alt_included", "alt_not_covered", "no_document", "roots", "unresolved_ids"],
        )

    def test_real_feed_counts(self):
        roots = [("r%d" % i, i) for i in range(341)]
        missing = ["m%d" % i for i in range(23)]
        summary = feedsbom.coverage_summary(roots, missing, 0)
        self.assertEqual(summary["roots"], 341)
        self.assertEqual(len(summary["no_document"]), 23)


class WriteSummaryTest(unittest.TestCase):
    def test_sorted_keys_and_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "coverage.json")
            summary = feedsbom.coverage_summary([("a", 1)], ["x"], 3)
            feedsbom.write_summary(path, summary)
            with open(path, encoding="utf-8") as f:
                text = f.read()
            self.assertEqual(json.loads(text), summary)
            keys = list(json.loads(text, object_pairs_hook=lambda p: p))
            self.assertEqual([k for k, _ in keys], sorted(k for k, _ in keys))
            self.assertEqual(os.listdir(tmp), ["coverage.json"])

    def test_replaces_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "coverage.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write("old")
            feedsbom.write_summary(path, {"roots": 1})
            with open(path, encoding="utf-8") as f:
                self.assertEqual(json.load(f), {"roots": 1})

    def test_replaces_symlink_without_writing_through(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "target.json")
            with open(target, "w", encoding="utf-8") as f:
                f.write("keep")
            path = os.path.join(tmp, "coverage.json")
            os.symlink(target, path)
            feedsbom.write_summary(path, {"roots": 1})
            self.assertFalse(os.path.islink(path))
            with open(target, encoding="utf-8") as f:
                self.assertEqual(f.read(), "keep")

    def test_a_failed_write_leaves_no_old_record_and_no_temp_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "coverage.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write("old")
            with self.assertRaises(TypeError):
                feedsbom.write_summary(path, {"roots": object()})
            self.assertEqual(os.listdir(tmp), [])

    def test_the_record_is_world_readable_like_the_document_beside_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "coverage.json")
            feedsbom.write_summary(path, {"roots": 1})
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o644)


class ScopeDependencyTest(unittest.TestCase):
    def test_world(self):
        self.assertEqual(
            feedsbom.scope_dependency("world", "img"),
            "meta-world-recipe-sbom:do_sbom_cve_check_recipe",
        )

    def test_image(self):
        self.assertEqual(
            feedsbom.scope_dependency("image", "avocado-image"),
            "avocado-image:do_sbom_cve_check",
        )

    def test_feed_is_ordered_inside_the_report_recipe(self):
        self.assertIsNone(feedsbom.scope_dependency("feed", "img"))

    def test_unknown_scope_names_the_valid_ones(self):
        with self.assertRaises(feedsbom.FeedSbomError) as ctx:
            feedsbom.scope_dependency("bogus", "img")
        message = str(ctx.exception)
        for name in ("world", "image", "feed"):
            self.assertIn(name, message)


if __name__ == "__main__":
    unittest.main()
