#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""avocado_sbom.spdxalias gives another multiconfig's documents aliases of
their own. Plain logic over parsed JSON, so the suite needs no build.

  cd meta-avocado-sbom/tests && PYTHONPATH=../lib python3 -m unittest discover -p 'test_*.py'
"""

import copy
import hashlib
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "lib"))

from avocado_sbom import spdxalias  # noqa: E402

DOC_ALIAS = (spdxalias.DOC_ALIAS_PREFIX + "linux-raspberrypi/recipe-linux-raspberrypi/"
             "linux-raspberrypi/UNIHASH/document/recipe-linux-raspberrypi")
OTHER_ALIAS = (spdxalias.DOC_ALIAS_PREFIX + "openssl-native/recipe-openssl-native/"
               "openssl-native/UNIHASH/document/recipe-openssl-native")


def alias_doc(doc_alias, refs):
    """A parsed document whose SpdxDocument carries doc_alias and whose one
    relationship refers to each of refs."""
    return {
        "@context": "https://spdx.org/rdf/3.0.1/spdx-context.jsonld",
        "@graph": [
            {"type": "SpdxDocument", "spdxId": "http://x/doc",
             "extension": [{"type": spdxalias.ALIAS_TYPE, spdxalias.ALIAS_KEY: doc_alias}]},
            {"type": "Relationship", "spdxId": "http://x/rel",
             "from": refs[0], "to": refs[1:], "relationshipType": "hasOutput"},
        ],
    }


class SpdxAliasTest(unittest.TestCase):
    def test_element_prefix_hashes_the_document_alias(self):
        self.assertEqual(
            spdxalias.element_prefix(DOC_ALIAS),
            spdxalias.ALIAS_PREFIX + hashlib.sha256(DOC_ALIAS.encode()).hexdigest() + "/")

    def test_document_alias_is_read_from_the_document_node(self):
        self.assertEqual(spdxalias.document_alias(alias_doc(DOC_ALIAS, ["a"])), DOC_ALIAS)

    def test_document_alias_absent(self):
        doc = alias_doc(DOC_ALIAS, ["a"])
        doc["@graph"][0]["extension"] = []
        for data in (doc, {}, {"@graph": "x"}, [], None):
            with self.subTest(data=data):
                self.assertIsNone(spdxalias.document_alias(data))

    def test_document_alias_ignores_other_nodes_and_extensions(self):
        doc = alias_doc(DOC_ALIAS, ["a"])
        doc["@graph"][0]["extension"].insert(0, {"type": "http://other", spdxalias.ALIAS_KEY: "no"})
        doc["@graph"][1]["extension"] = [{"type": spdxalias.ALIAS_TYPE, spdxalias.ALIAS_KEY: "rel"}]
        self.assertEqual(spdxalias.document_alias(doc), DOC_ALIAS)

    def test_multiconfig_alias_cannot_be_a_pn(self):
        new = spdxalias.multiconfig_alias(DOC_ALIAS, "raspberrypi-6_6")
        self.assertEqual(new, spdxalias.DOC_ALIAS_PREFIX + "multiconfig:raspberrypi-6_6/"
                         + DOC_ALIAS[len(spdxalias.DOC_ALIAS_PREFIX):])
        self.assertNotEqual(spdxalias.multiconfig_alias(DOC_ALIAS, "other"), new)

    def test_map_holds_each_alias_and_its_prefix(self):
        mapping = spdxalias.multiconfig_map([DOC_ALIAS, None, ""], "mc")
        new = spdxalias.multiconfig_alias(DOC_ALIAS, "mc")
        self.assertEqual(mapping, {
            DOC_ALIAS: new,
            spdxalias.element_prefix(DOC_ALIAS): spdxalias.element_prefix(new),
        })

    def test_remap_rewrites_aliases_of_mapped_documents_only(self):
        mine = spdxalias.element_prefix(DOC_ALIAS)
        other = spdxalias.element_prefix(OTHER_ALIAS)
        data = alias_doc(DOC_ALIAS, [mine + "linux-raspberrypi/UNIHASH/build/recipe",
                                     other + "openssl-native/UNIHASH/build/recipe",
                                     "http://spdx.org/spdxdocs/linux/abc/package/kernel"])
        before = copy.deepcopy(data)
        mapping = spdxalias.multiconfig_map([DOC_ALIAS], "mc")
        out = spdxalias.remap(data, mapping)
        self.assertEqual(data, before, "the input is left as it was")
        new_prefix = spdxalias.element_prefix(spdxalias.multiconfig_alias(DOC_ALIAS, "mc"))
        rel = out["@graph"][1]
        self.assertEqual(rel["from"], new_prefix + "linux-raspberrypi/UNIHASH/build/recipe")
        self.assertEqual(rel["to"], before["@graph"][1]["to"])
        self.assertEqual(out["@graph"][0]["extension"][0][spdxalias.ALIAS_KEY],
                         spdxalias.multiconfig_alias(DOC_ALIAS, "mc"))
        self.assertEqual(out["@context"], before["@context"])

    def test_remap_leaves_keys_and_non_strings(self):
        mine = spdxalias.element_prefix(DOC_ALIAS)
        data = {mine + "k": [1, None, True, {"x": 2.5}]}
        self.assertEqual(spdxalias.remap(data, spdxalias.multiconfig_map([DOC_ALIAS], "mc")), data)

    def test_remap_needs_the_whole_prefix(self):
        mine = spdxalias.element_prefix(DOC_ALIAS)
        mapping = spdxalias.multiconfig_map([DOC_ALIAS], "mc")
        for value in (mine[:-1], mine[:-1] + "0/x", spdxalias.ALIAS_PREFIX + "nohash"):
            with self.subTest(value=value):
                self.assertEqual(spdxalias.remap(value, mapping), value)

    def test_alias_recipe_is_the_pn_after_the_hash(self):
        prefix = spdxalias.element_prefix(spdxalias.DOC_ALIAS_PREFIX + "jsoncpp-native/UNIHASH/static")
        self.assertEqual(spdxalias.alias_recipe(prefix + "jsoncpp-native/UNIHASH/recipe-jsoncpp-native"),
                         "jsoncpp-native")
        # A qualified alias keeps the PN in place.
        mapped = spdxalias.multiconfig_map([spdxalias.DOC_ALIAS_PREFIX + "x/UNIHASH/static"], "rt")
        value = spdxalias.remap(spdxalias.element_prefix(spdxalias.DOC_ALIAS_PREFIX + "x/UNIHASH/static")
                                + "linux-yocto-rt/UNIHASH/recipe-linux-yocto-rt", mapped)
        self.assertEqual(spdxalias.alias_recipe(value), "linux-yocto-rt")

    def test_alias_recipe_of_anything_else_is_none(self):
        for value in (None, 7, "", "http://spdx.org/spdxdocs/x/UNIHASH/recipe-x",
                      spdxalias.ALIAS_PREFIX, spdxalias.ALIAS_PREFIX + "abc",
                      spdxalias.ALIAS_PREFIX + "abc/x", spdxalias.ALIAS_PREFIX + "abc//x"):
            with self.subTest(value=value):
                self.assertIsNone(spdxalias.alias_recipe(value))


if __name__ == "__main__":
    unittest.main()
