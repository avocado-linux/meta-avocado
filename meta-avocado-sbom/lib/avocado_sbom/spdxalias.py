# SPDX-License-Identifier: Apache-2.0

"""Give another multiconfig's SPDX documents identity aliases of their own.

create-spdx-3.0 gives each element an identity alias that leaves the task hash
out: the document's alias, and for every element in it a prefix hashed from
that alias. Documents link to each other by these aliases. A recipe built in
two multiconfigs writes two documents under one name for one PN, so both
documents carry the same aliases, and a link from one resolves to whichever
document was indexed last.

On scarthgap that matters for the feed scan: a package document names the build
that produced it and the CVEs its VEX statements are about by alias, so the
alternate kernel's packages would bind to the default kernel's build. The
alternate multiconfig's documents are loaded as JSON, their aliases are
qualified with the multiconfig here, and only then deserialized, so links
between them resolve to each other and every other link is left alone.

Plain logic over parsed JSON. It imports neither oe nor bb; the constants
mirror oe.sbom30, and the tests check them against it when given OE-core.
"""

import hashlib

# oe.sbom30.OE_ALIAS_PREFIX and OE_DOC_ALIAS_PREFIX.
ALIAS_PREFIX = "http://spdxdocs.org/openembedded-alias/by-doc-hash/"
DOC_ALIAS_PREFIX = "http://spdxdocs.org/openembedded-alias/doc/"
# How oe.sbom30.OEIdAliasExtension serializes.
ALIAS_TYPE = "https://rdf.openembedded.org/spdx/3.0/id-alias"
ALIAS_KEY = "https://rdf.openembedded.org/spdx/3.0/alias"


def element_prefix(doc_alias):
    """The prefix of every element alias in the document whose alias is doc_alias.

    oe.sbom30.ObjectSet.alias_prefix: the hash is oe.sbom30.hash_id.
    """
    return ALIAS_PREFIX + hashlib.sha256(doc_alias.encode("utf-8")).hexdigest() + "/"


def document_alias(data):
    """The SpdxDocument's identity alias in a parsed JSON-LD document, or None."""
    graph = data.get("@graph") if isinstance(data, dict) else None
    if not isinstance(graph, list):
        return None
    for node in graph:
        if not isinstance(node, dict) or node.get("type") != "SpdxDocument":
            continue
        for ext in node.get("extension") or []:
            if isinstance(ext, dict) and ext.get("type") == ALIAS_TYPE:
                alias = ext.get(ALIAS_KEY)
                if isinstance(alias, str) and alias:
                    return alias
    return None


def multiconfig_alias(doc_alias, mc):
    """doc_alias qualified with the multiconfig. "multiconfig:" cannot open a PN."""
    rest = doc_alias[len(DOC_ALIAS_PREFIX):] if doc_alias.startswith(DOC_ALIAS_PREFIX) else doc_alias
    return "%smulticonfig:%s/%s" % (DOC_ALIAS_PREFIX, mc, rest)


def multiconfig_map(doc_aliases, mc):
    """{old: new} for each document alias and its element prefix.

    Built from every document loaded from one multiconfig, so a link from one of
    them to another follows both into the multiconfig's namespace.
    """
    mapping = {}
    for alias in doc_aliases:
        if not alias:
            continue
        new = multiconfig_alias(alias, mc)
        mapping[alias] = new
        mapping[element_prefix(alias)] = element_prefix(new)
    return mapping


def remap(value, mapping):
    """value with every string mapping names rewritten: a whole document alias,
    or an element alias by its prefix. Everything else is returned as it is.
    """
    if isinstance(value, str):
        new = mapping.get(value)
        if new is not None:
            return new
        if value.startswith(ALIAS_PREFIX):
            cut = value.find("/", len(ALIAS_PREFIX))
            if cut != -1:
                prefix = mapping.get(value[:cut + 1])
                if prefix is not None:
                    return prefix + value[cut + 1:]
        return value
    if isinstance(value, list):
        return [remap(v, mapping) for v in value]
    if isinstance(value, dict):
        return {k: remap(v, mapping) for k, v in value.items()}
    return value
