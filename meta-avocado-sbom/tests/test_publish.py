#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""Prove the publication gate by mutation.

Each test plants the assessment somewhere and asserts the filter removes it, or
that the gate catches what the filter did not. The gate is what the ticket
freezes: no CVE identifier in the emitted document, whatever field carried it.

  python3 -m unittest discover -s meta-avocado-sbom/tests -p 'test_*.py'
"""

import copy
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

from avocado_sbom import publish  # noqa: E402

SPDX_DIR = os.path.join(HERE, "fixtures", "spdx")
SPDX30 = os.path.join(SPDX_DIR, "recipe-example-3.0.1.spdx.json")
SPDX22 = os.path.join(SPDX_DIR, "recipe-example-2.2.spdx.json")
# do_create_image_sbom_spdx writes this one beside the image, not into
# deploy/spdx/, and it is the only one rooted in a software_Sbom.
IMAGE30 = os.path.join(SPDX_DIR, "image-sbom-3.0.1.spdx.json")

# Derived: the tree tests copy every fixture in, so a literal breaks each time
# the suite gains a shape.
FIXTURE_DOCS = len([n for n in os.listdir(SPDX_DIR) if n.endswith(".spdx.json")])

def load(path):
    with open(path) as f:
        return json.load(f)

def nodes(doc):
    return {n.get("spdxId"): n for n in doc["@graph"]}

class FilterTests(unittest.TestCase):
    def setUp(self):
        self.stats = publish.Stats()

    def filtered(self, doc):
        out = publish.filter_document(copy.deepcopy(doc), self.stats)
        self.assertEqual(publish.leaks(out), [])
        return out

    def test_spdx30_fixture_filters_clean(self):
        self.filtered(load(SPDX30))

    def test_spdx22_fixture_filters_clean(self):
        self.filtered(load(SPDX22))

    def test_image_sbom_fixture_filters_clean(self):
        self.filtered(load(IMAGE30))

    def test_fixtures_actually_carry_the_assessment(self):
        # Without this the two tests above pass against empty documents.
        for path in (SPDX30, SPDX22, IMAGE30):
            self.assertTrue(publish.leaks(load(path)), "%s carries no CVE" % path)

    def test_gate_is_not_keyed_on_field_names(self):
        doc = load(SPDX30)
        doc["@graph"][1]["software_homePage"] = "https://example.invalid/CVE-2021-42380"
        out = publish.filter_document(doc, self.stats)
        found = publish.leaks(out)
        self.assertTrue(found, "an unhandled field passed the gate")
        self.assertIn("CVE-2021-42380", found[0])

    def test_security_nodes_dropped(self):
        out = self.filtered(load(SPDX30))
        self.assertEqual(
            [n for n in out["@graph"] if n["type"].startswith("security_")], []
        )

    def test_cross_document_vulnerability_relationship_dropped(self):
        # Its "to" is an alias URI owned by another document, so nothing local
        # identifies the referent - only the relationship type and the URI do.
        out = self.filtered(load(SPDX30))
        self.assertNotIn(
            "hasAssociatedVulnerability",
            [n.get("relationshipType") for n in out["@graph"]],
        )

    def test_relationship_left_empty_is_dropped(self):
        # Its one target is a vulnerability, so "to": [] would relate nothing.
        out = self.filtered(load(SPDX30))
        self.assertNotIn(
            "http://spdx.org/spdxdocs/example/relationship/3", nodes(out)
        )

    def test_surviving_relationship_keeps_its_other_targets(self):
        out = self.filtered(load(SPDX30))
        rel = nodes(out)["http://spdx.org/spdxdocs/example/relationship/1"]
        self.assertEqual(len(rel["to"]), 2)

    def test_lowercase_identifier_is_caught(self):
        # A case-sensitive gate lets these through *clean*: the fail-open case.
        doc = load(SPDX30)
        nodes(doc)["http://spdx.org/spdxdocs/example/source/2"]["name"] = \
            "cve-2014-8139-crc-overflow.patch"
        out = self.filtered(doc)
        self.assertEqual(
            nodes(out)["http://spdx.org/spdxdocs/example/source/2"]["name"],
            "CVE-REDACTED-crc-overflow.patch",
        )

    def test_relationship_with_mixed_targets_keeps_the_real_ones(self):
        # Naming a vulnerability alongside real files must cost the document
        # the vulnerability, not the file edges.
        doc = load(SPDX30)
        nodes(doc)["http://spdx.org/spdxdocs/example/relationship/1"]["to"].append(
            "http://spdx.org/spdxdocs/example/vulnerability/CVE-2019-1010026"
        )
        out = self.filtered(doc)
        rel = nodes(out)["http://spdx.org/spdxdocs/example/relationship/1"]
        self.assertEqual(
            rel["to"],
            [
                "http://spdx.org/spdxdocs/example/source/1",
                "http://spdx.org/spdxdocs/example/source/2",
            ],
        )

    # Nothing in deploy/spdx/ has the per-image shape: a collection root, both
    # VEX flavours, LifecycleScoped relationships.

    def test_image_roots_survive_and_still_reach_the_inventory(self):
        out = self.filtered(load(IMAGE30))
        kept = nodes(out)
        doc = kept["http://spdx.org/spdxdocs/example/image/document"]
        sbom = kept["http://spdx.org/spdxdocs/example/image/sbom"]
        self.assertEqual(doc["rootElement"], [sbom["spdxId"]])
        self.assertEqual(
            sbom["rootElement"],
            [
                "http://spdx.org/spdxdocs/example/image/package/image",
                "http://spdx.org/spdxdocs/example/image/artifact/erofs",
            ],
        )
        self.assertEqual(
            kept["http://spdx.org/spdxdocs/example/image/artifact/erofs"][
                "verifiedUsing"
            ][0]["hashValue"],
            "ee",
        )

    def test_both_vex_flavours_dropped_and_the_contains_edge_kept(self):
        out = self.filtered(load(IMAGE30))
        self.assertEqual(
            [n for n in out["@graph"] if n["type"].startswith("security_")], []
        )
        rel = nodes(out)["http://spdx.org/spdxdocs/example/image/relationship/1"]
        self.assertEqual(
            rel["to"], ["http://spdx.org/spdxdocs/example/image/package/example"]
        )

    def test_document_whose_only_cve_is_a_filename(self):
        # 2 of the 4,762 documents carrying an identifier hold no security_*
        # node at all, just patch filenames. Redaction is what reaches them.
        doc = {
            "@graph": [
                {"type": "software_Package",
                 "spdxId": "http://spdx.org/spdxdocs/example/package/ptest",
                 "name": "openssl-ptest"},
                {"type": "software_File",
                 "spdxId": "http://spdx.org/spdxdocs/example/source/patch",
                 "name": "CVE-2024-28085-0001.patch",
                 "verifiedUsing": [{"type": "Hash", "algorithm": "sha256",
                                    "hashValue": "cc"}]},
            ]
        }
        out = self.filtered(doc)
        self.assertEqual(self.stats.nodes_dropped, 0)
        self.assertEqual(self.stats.names_redacted, 1)
        self.assertEqual(len(out["@graph"]), 2)

    def test_patch_file_kept_with_its_checksum(self):
        out = self.filtered(load(SPDX30))
        node = nodes(out)["http://spdx.org/spdxdocs/example/source/2"]
        self.assertEqual(node["name"], "CVE-REDACTED-0001.patch")
        self.assertEqual(node["verifiedUsing"][0]["hashValue"], "bb")
        self.assertEqual(self.stats.names_redacted, 1)

    def test_spdx22_source_info_dropped(self):
        out = self.filtered(load(SPDX22))
        self.assertNotIn("sourceInfo", out["packages"][0])

    def test_spdx22_package_survives_the_drop(self):
        # Dropping the node rather than the field would empty the document.
        out = self.filtered(load(SPDX22))
        self.assertEqual(out["packages"][0]["name"], "example")
        self.assertEqual(out["packages"][0]["versionInfo"], "1.0")

    def test_spdx22_security_external_ref_dropped_others_kept(self):
        out = self.filtered(load(SPDX22))
        refs = out["packages"][0]["externalRefs"]
        self.assertEqual([r["referenceCategory"] for r in refs], ["PACKAGE-MANAGER"])

    def test_spdx22_patch_file_name_redacted(self):
        out = self.filtered(load(SPDX22))
        self.assertEqual(out["files"][1]["fileName"], "CVE-REDACTED-0001.patch")

class TreeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.in_dir = os.path.join(self.tmp, "in")
        self.out_dir = os.path.join(self.tmp, "out")
        shutil.copytree(SPDX_DIR, os.path.join(self.in_dir, "cortexa57", "recipes"))
        self.stats = publish.Stats()
        self.messages = []

    def run_filter(self):
        publish.run(self.in_dir, self.out_dir, self.stats, self.messages.append)

    def test_tree_is_mirrored(self):
        self.run_filter()
        self.assertEqual(self.stats.documents, FIXTURE_DOCS)
        self.assertEqual(self.stats.leaked, 0)
        for name in os.listdir(os.path.join(SPDX_DIR)):
            self.assertTrue(
                os.path.isfile(
                    os.path.join(self.out_dir, "cortexa57", "recipes", name)
                )
            )

    def test_symlinked_index_is_not_followed(self):
        # by-hash/, by-namespace/ and by-spdxid-hash/ mirror the arch trees.
        index = os.path.join(self.in_dir, "by-hash")
        os.symlink(os.path.join(self.in_dir, "cortexa57"), index)
        os.symlink(
            os.path.join(self.in_dir, "cortexa57", "recipes",
                         os.path.basename(SPDX30)),
            os.path.join(self.in_dir, "cortexa57", "aliased.spdx.json"),
        )
        self.run_filter()
        self.assertEqual(self.stats.documents, FIXTURE_DOCS)
        self.assertEqual(self.stats.symlinks_skipped, 1)
        self.assertFalse(os.path.exists(os.path.join(self.out_dir, "by-hash")))

    def test_leaking_document_is_not_written(self):
        path = os.path.join(self.in_dir, "cortexa57", "recipes", "leak.spdx.json")
        with open(path, "w") as f:
            json.dump({"@graph": [{"type": "software_Package",
                                   "software_homePage": "CVE-2021-42380"}]}, f)
        self.run_filter()
        self.assertEqual(self.stats.leaked, 1)
        self.assertFalse(
            os.path.exists(
                os.path.join(self.out_dir, "cortexa57", "recipes", "leak.spdx.json")
            )
        )
        self.assertTrue(any("CVE-2021-42380" in m for m in self.messages))

    def test_malformed_document_does_not_abandon_the_tree(self):
        # Valid JSON of the wrong shape. One of these part-way through a
        # 13,000-document tree must not leave the rest unwritten.
        with open(os.path.join(self.in_dir, "cortexa57", "recipes",
                               "bad.spdx.json"), "w") as f:
            f.write("[1, 2, 3]")
        self.run_filter()
        self.assertEqual(self.stats.unreadable, 1)
        for name in ("recipe-example-3.0.1.spdx.json", "recipe-example-2.2.spdx.json"):
            self.assertTrue(os.path.isfile(
                os.path.join(self.out_dir, "cortexa57", "recipes", name)))
        self.assertTrue(any("not filterable" in m for m in self.messages))

    def test_check_mode_writes_nothing(self):
        publish.run(self.in_dir, None, self.stats, self.messages.append)
        self.assertEqual(self.stats.documents, FIXTURE_DOCS)
        self.assertFalse(os.path.exists(self.out_dir))
        # The fixtures are unfiltered, so the gate has to fail on every one.
        self.assertEqual(self.stats.leaked, FIXTURE_DOCS)

if __name__ == "__main__":
    unittest.main()
