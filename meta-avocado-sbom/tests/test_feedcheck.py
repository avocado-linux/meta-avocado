#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""feedcheck turns the feed contract into named checks over a build tree.

The trees here are small fixtures written to a temporary directory, so no build
is needed. Each negative test breaks one thing and expects exit status 1 with
that check, and only that check, failing.

  python3 -m unittest discover -s meta-avocado-sbom/tests -p 'test_feedcheck.py'
"""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

from avocado_sbom import feedcheck  # noqa: E402

MACHINE = "avocado-raspberrypi5"
SHORT = "raspberrypi5"
CONTEXT = "https://spdx.org/rdf/3.0.1/spdx-context.jsonld"
COVERAGE_KEYS = ("roots", "no_document", "unresolved_ids", "alt_included",
                 "alt_not_covered")
REPORT_KEYS = ("version", "generated", "status", "counts", "recipes")
RPM_KEYS = ("version", "generated", "machine", "packages")

def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f)

def issues(unpatched=0, ignored=0, patched=0):
    out = []
    for status, count in (("Unpatched", unpatched), ("Ignored", ignored),
                          ("Patched", patched)):
        out += [{"id": "CVE-2000-%s%d" % (status[0], n), "status": status}
                for n in range(count)]
    return out

def manifest(*packages):
    return {"version": 1, "package": [
        {"name": n, "version": v, "issue": i} for n, v, i in packages]}

IMAGE_PACKAGES = (
    ("acl", "2.3.2", issues(patched=2)),
    ("linux-raspberrypi", "6.12.87+git", issues(unpatched=3, ignored=1)),
)

class Tree:
    """A build tree whose feed passes every check until a test breaks it."""

    def __init__(self, test):
        holder = tempfile.TemporaryDirectory()
        test.addCleanup(holder.cleanup)
        self.tmp = holder.name
        self.deploy = os.path.join(self.tmp, "deploy")
        self.images = os.path.join(self.deploy, "images", MACHINE)
        self.document = os.path.join(
            self.images, "avocado-feed-%s.spdx.json" % SHORT)
        self.coverage = os.path.join(
            self.images, "avocado-feed-%s.coverage.json" % SHORT)
        self.feed_manifest = os.path.join(
            self.images, "avocado-feed-%s.sbom-cve-check.yocto.json" % SHORT)
        self.report = os.path.join(
            self.deploy, "avocado-cve", "avocado-cve-report-%s.json" % MACHINE)
        self.rpms = os.path.join(
            self.deploy, "avocado-cve", "avocado-rpm-manifest-%s.json" % MACHINE)
        self.image_manifest = os.path.join(self.tmp, "image", "manifest.json")
        self.image_report = os.path.join(self.tmp, "image", "report.json")
        self.image_rpms = os.path.join(self.tmp, "image", "rpms.json")

        write_json(self.document, self.sbom_document(2, sboms=1))
        write_json(self.coverage, {
            "roots": 2, "no_document": [], "unresolved_ids": 0,
            "alt_included": [], "alt_not_covered": []})
        write_json(self.feed_manifest, manifest(*IMAGE_PACKAGES, (
            "zlib", "1.3", issues())))
        write_json(self.image_manifest, manifest(*IMAGE_PACKAGES))
        write_json(self.report, {k: 1 for k in REPORT_KEYS})
        write_json(self.rpms, {k: 1 for k in RPM_KEYS})
        write_json(self.image_report, {k: 2 for k in REPORT_KEYS})
        write_json(self.image_rpms, {k: 2 for k in RPM_KEYS})

    @staticmethod
    def sbom_document(roots, sboms=1, context=CONTEXT):
        graph = [{"type": "software_Sbom", "rootElement": ["r%d" % n
                                                          for n in range(roots)]}
                 for _ in range(sboms)]
        graph.append({"type": "software_Package", "name": "acl"})
        return {"@context": context, "@graph": graph}

    def run(self, *extra):
        argv = ["--tmpdir", self.tmp, "--machine", MACHINE, *extra]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = feedcheck.main(argv)
        return code, out.getvalue()

    def run_all(self):
        return self.run("--image-manifest", self.image_manifest,
                        "--image-report", self.image_report,
                        "--image-rpm-manifest", self.image_rpms)

class FeedCheckTest(unittest.TestCase):
    def failed(self, output):
        return [line.split(":")[0][5:] for line in output.splitlines()
                if line.startswith("FAIL ")]

    def test_good_tree_passes_with_the_count_of_checks_run(self):
        code, out = Tree(self).run()
        self.assertEqual(code, 0, out)
        self.assertEqual(out.splitlines()[-1], "checks: 6/6 passed")

    def test_every_option_adds_its_checks_to_the_count(self):
        code, out = Tree(self).run_all()
        self.assertEqual(code, 0, out)
        self.assertEqual(out.splitlines()[-1], "checks: 10/10 passed")
        self.assertEqual(len([l for l in out.splitlines()
                              if l.startswith("ok ")]), 10)

    def test_missing_document_fails(self):
        tree = Tree(self)
        os.remove(tree.document)
        code, out = tree.run()
        self.assertEqual(code, 1)
        self.assertEqual(self.failed(out),
                         ["feed-document-exists", "feed-document-jsonld",
                          "feed-document-roots"])
        self.assertIn("checks: 3/6 passed", out)

    def test_document_without_the_spdx_context_fails(self):
        tree = Tree(self)
        write_json(tree.document, Tree.sbom_document(2, context="urn:other"))
        code, out = tree.run()
        self.assertEqual(code, 1)
        self.assertEqual(self.failed(out), ["feed-document-jsonld"])

    def test_two_sbom_elements_fail(self):
        tree = Tree(self)
        write_json(tree.document, Tree.sbom_document(2, sboms=2))
        code, out = tree.run()
        self.assertEqual(code, 1)
        self.assertIn("feed-document-jsonld", self.failed(out))

    def test_root_count_differing_from_coverage_fails(self):
        tree = Tree(self)
        write_json(tree.document, Tree.sbom_document(3))
        code, out = tree.run()
        self.assertEqual(code, 1)
        self.assertEqual(self.failed(out), ["feed-document-roots"])
        self.assertIn("3", out)

    def test_unparseable_document_fails_without_a_traceback(self):
        tree = Tree(self)
        with open(tree.document, "w") as f:
            f.write("{not json")
        code, out = tree.run()
        self.assertEqual(code, 1)
        self.assertIn("feed-document-jsonld", self.failed(out))

    def test_missing_coverage_record_fails(self):
        tree = Tree(self)
        os.remove(tree.coverage)
        code, out = tree.run()
        self.assertEqual(code, 1)
        self.assertEqual(self.failed(out),
                         ["feed-document-roots", "coverage-record"])

    def test_coverage_record_missing_a_key_fails(self):
        tree = Tree(self)
        write_json(tree.coverage, {k: 2 if k == "roots" else []
                                   for k in COVERAGE_KEYS if k != "no_document"})
        code, out = tree.run()
        self.assertEqual(code, 1)
        self.assertEqual(self.failed(out), ["coverage-record"])
        self.assertIn("no_document", out)

    def test_coverage_record_with_an_extra_key_fails(self):
        tree = Tree(self)
        write_json(tree.coverage, {**{k: 2 if k == "roots" else []
                                      for k in COVERAGE_KEYS}, "extra": 1})
        code, out = tree.run()
        self.assertEqual(code, 1)
        self.assertEqual(self.failed(out), ["coverage-record"])

    def test_missing_feed_manifest_fails(self):
        tree = Tree(self)
        os.remove(tree.feed_manifest)
        code, out = tree.run()
        self.assertEqual(code, 1)
        self.assertEqual(self.failed(out), ["feed-manifest"])

    def test_document_copy_under_deploy_rpm_fails(self):
        tree = Tree(self)
        write_json(os.path.join(tree.deploy, "rpm", "noarch",
                                os.path.basename(tree.document)), {})
        code, out = tree.run()
        self.assertEqual(code, 1)
        self.assertEqual(self.failed(out), ["no-document-copies"])

    def test_document_copy_under_deploy_spdx_fails(self):
        tree = Tree(self)
        write_json(os.path.join(tree.deploy, "spdx", "3.0.1", "x",
                                os.path.basename(tree.document)), {})
        code, out = tree.run()
        self.assertEqual(code, 1)
        self.assertEqual(self.failed(out), ["no-document-copies"])

    def test_other_spdx_files_in_those_trees_pass(self):
        tree = Tree(self)
        write_json(os.path.join(tree.deploy, "spdx", "3.0.1", "x",
                                "acl.spdx.json"), {})
        self.assertEqual(tree.run()[0], 0)

    def test_report_with_other_top_level_keys_than_the_image_report_fails(self):
        tree = Tree(self)
        write_json(tree.report, {k: 1 for k in REPORT_KEYS[:-1]})
        code, out = tree.run("--image-report", tree.image_report)
        self.assertEqual(code, 1)
        self.assertEqual(self.failed(out), ["report-keys"])

    def test_missing_report_fails_when_the_image_report_is_given(self):
        tree = Tree(self)
        os.remove(tree.report)
        code, out = tree.run("--image-report", tree.image_report)
        self.assertEqual(code, 1)
        self.assertEqual(self.failed(out), ["report-keys"])

    def test_rpm_manifest_with_other_keys_than_the_image_one_fails(self):
        tree = Tree(self)
        write_json(tree.rpms, {k: 1 for k in RPM_KEYS + ("extra",)})
        code, out = tree.run("--image-rpm-manifest", tree.image_rpms)
        self.assertEqual(code, 1)
        self.assertEqual(self.failed(out), ["rpm-manifest-keys"])

    def test_missing_image_input_fails_rather_than_being_skipped(self):
        tree = Tree(self)
        os.remove(tree.image_manifest)
        code, out = tree.run("--image-manifest", tree.image_manifest)
        self.assertEqual(code, 1)
        self.assertEqual(self.failed(out), ["image-recipes", "image-kernels"])

    def test_feed_manifest_lacking_an_image_recipe_fails(self):
        tree = Tree(self)
        write_json(tree.feed_manifest, manifest(IMAGE_PACKAGES[1]))
        code, out = tree.run("--image-manifest", tree.image_manifest)
        self.assertEqual(code, 1)
        self.assertEqual(self.failed(out), ["image-recipes"])
        self.assertIn("acl", out)

    def test_recipe_at_another_version_counts_as_lacking(self):
        tree = Tree(self)
        write_json(tree.feed_manifest, manifest(
            ("acl", "2.3.3", issues()), IMAGE_PACKAGES[1]))
        code, out = tree.run("--image-manifest", tree.image_manifest)
        self.assertEqual(code, 1)
        self.assertEqual(self.failed(out), ["image-recipes"])

    def test_epoch_prefix_in_either_manifest_does_not_hide_a_recipe(self):
        tree = Tree(self)
        write_json(tree.feed_manifest, manifest(
            ("acl", "1_2.3.2", issues()), IMAGE_PACKAGES[1]))
        self.assertEqual(
            tree.run("--image-manifest", tree.image_manifest)[0], 0)

    def test_kernel_unpatched_count_differing_fails(self):
        tree = Tree(self)
        write_json(tree.feed_manifest, manifest(
            IMAGE_PACKAGES[0],
            ("linux-raspberrypi", "6.12.87+git", issues(unpatched=4, ignored=1))))
        code, out = tree.run("--image-manifest", tree.image_manifest)
        self.assertEqual(code, 1)
        self.assertEqual(self.failed(out), ["image-kernels"])
        self.assertIn("linux-raspberrypi", out)

    def test_kernel_ignored_count_differing_fails(self):
        tree = Tree(self)
        write_json(tree.feed_manifest, manifest(
            IMAGE_PACKAGES[0],
            ("linux-raspberrypi", "6.12.87+git", issues(unpatched=3))))
        code, out = tree.run("--image-manifest", tree.image_manifest)
        self.assertEqual(code, 1)
        self.assertEqual(self.failed(out), ["image-kernels"])

    def test_patched_count_differences_do_not_matter(self):
        tree = Tree(self)
        write_json(tree.feed_manifest, manifest(
            IMAGE_PACKAGES[0],
            ("linux-raspberrypi", "6.12.87+git",
             issues(unpatched=3, ignored=1, patched=9))))
        self.assertEqual(
            tree.run("--image-manifest", tree.image_manifest)[0], 0)

    def test_only_linux_dash_recipes_are_kernels(self):
        tree = Tree(self)
        write_json(tree.image_manifest, manifest(
            ("acl", "2.3.2", issues(unpatched=5)), IMAGE_PACKAGES[1]))
        write_json(tree.feed_manifest, manifest(
            ("acl", "2.3.2", issues(unpatched=1)), IMAGE_PACKAGES[1]))
        self.assertEqual(
            tree.run("--image-manifest", tree.image_manifest)[0], 0)

    def test_image_manifest_with_no_kernel_fails(self):
        tree = Tree(self)
        write_json(tree.image_manifest, manifest(IMAGE_PACKAGES[0]))
        code, out = tree.run("--image-manifest", tree.image_manifest)
        self.assertEqual(code, 1)
        self.assertEqual(self.failed(out), ["image-kernels"])

    def test_firmware_and_headers_are_not_kernels(self):
        tree = Tree(self)
        only_non_kernels = manifest(
            IMAGE_PACKAGES[0],
            ("linux-firmware-rpidistro", "20240101", issues(unpatched=1)),
            ("linux-libc-headers", "6.12", issues(unpatched=1)))
        write_json(tree.image_manifest, only_non_kernels)
        write_json(tree.feed_manifest, only_non_kernels)
        code, out = tree.run("--image-manifest", tree.image_manifest)
        self.assertEqual(code, 1)
        self.assertEqual(self.failed(out), ["image-kernels"])

    def test_a_context_list_holding_the_spdx_context_passes(self):
        tree = Tree(self)
        write_json(tree.document, Tree.sbom_document(2, context=["urn:x", CONTEXT]))
        self.assertEqual(tree.run()[0], 0)

    def test_a_spdx_prefixed_url_that_is_not_a_context_file_fails(self):
        tree = Tree(self)
        write_json(tree.document, Tree.sbom_document(
            2, context="https://spdx.org/rdf/3.0.1/model"))
        code, out = tree.run()
        self.assertEqual(code, 1)
        self.assertEqual(self.failed(out), ["feed-document-jsonld"])

    def test_missing_rpm_manifest_fails_when_the_image_one_is_given(self):
        tree = Tree(self)
        os.remove(tree.rpms)
        code, out = tree.run("--image-rpm-manifest", tree.image_rpms)
        self.assertEqual(code, 1)
        self.assertEqual(self.failed(out), ["rpm-manifest-keys"])

    def test_a_boolean_roots_value_does_not_equal_a_root_count_of_one(self):
        tree = Tree(self)
        write_json(tree.document, Tree.sbom_document(1))
        write_json(tree.coverage, {
            "roots": True, "no_document": [], "unresolved_ids": 0,
            "alt_included": [], "alt_not_covered": []})
        code, out = tree.run()
        self.assertEqual(code, 1)
        self.assertIn("feed-document-roots", self.failed(out))
        self.assertIn("coverage-record", self.failed(out))

    def test_coverage_values_of_the_wrong_type_fail(self):
        for key, bad in (("no_document", "x"), ("unresolved_ids", "3"),
                         ("alt_included", {}), ("alt_not_covered", 0)):
            tree = Tree(self)
            record = {"roots": 2, "no_document": [], "unresolved_ids": 0,
                      "alt_included": [], "alt_not_covered": []}
            record[key] = bad
            write_json(tree.coverage, record)
            code, out = tree.run()
            self.assertEqual(code, 1, key)
            self.assertEqual(self.failed(out), ["coverage-record"], key)

    def test_an_unhashable_issue_status_fails_without_a_traceback(self):
        tree = Tree(self)
        write_json(tree.feed_manifest, {"package": [
            {"name": "acl", "version": "2.3.2", "issue": [{"status": ["x"]}]},
            {"name": "linux-raspberrypi", "version": "6.12.87+git",
             "issue": issues(unpatched=3, ignored=1)}]})
        code, out = tree.run("--image-manifest", tree.image_manifest)
        self.assertEqual(code, 0, out)
        self.assertEqual(out.splitlines()[-1], "checks: 8/8 passed")

    def test_an_image_manifest_without_usable_entries_fails(self):
        tree = Tree(self)
        write_json(tree.image_manifest, {"package": [{"version": "1"}, "x"]})
        code, out = tree.run("--image-manifest", tree.image_manifest)
        self.assertEqual(code, 1)
        self.assertIn("image-recipes", self.failed(out))

if __name__ == "__main__":
    unittest.main()
