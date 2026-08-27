# SPDX-License-Identifier: Apache-2.0

"""Filter a build's SPDX documents down to a publishable inventory.

The gate is on CVE identifiers anywhere in the output, not on the field that
carried them: 2.2 puts the assessment in free-text sourceInfo and 3.0.1 in
security_* objects, so a gate keyed on either name passes silently on the other.
"""

import json
import os
import re

from avocado_sbom.report import Stats as _Stats, write_report

# Case-insensitive: upstream ships lowercase patch names too
# (unzip's cve-2014-8139-crc-overflow.patch).
CVE_RE = re.compile(r"CVE-\d{4}-\d{4,}", re.IGNORECASE)
REDACTED = "CVE-REDACTED"

class Stats(_Stats):
    _NAMES = (
        "documents",
        "symlinks_skipped",
        "unreadable",
        "nodes_dropped",
        "relationships_dropped",
        "fields_dropped",
        "names_redacted",
        "leaked",
    )

# A patch is named for the CVE it fixes, so the file list carries the assessment
# too. The file is inventory and stays; only the identifier goes.
NAME_FIELDS = ("name", "fileName")

def _redact_name(node, stats):
    for field in NAME_FIELDS:
        name = node.get(field)
        if isinstance(name, str) and CVE_RE.search(name):
            node[field] = CVE_RE.sub(REDACTED, name)
            stats.names_redacted += 1

def _to_list(value):
    if isinstance(value, list):
        return value
    return [] if value is None else [value]

def _filter_graph(doc, stats):
    """SPDX 3.0.1: a flat @graph of typed nodes."""
    graph = doc.get("@graph")
    if not isinstance(graph, list):
        return doc

    kept = []
    dropped_ids = set()
    for node in graph:
        if not isinstance(node, dict):
            kept.append(node)
            continue

        node_type = node.get("type")
        if isinstance(node_type, str) and node_type.startswith("security_"):
            dropped_ids.add(node.get("spdxId"))
            stats.nodes_dropped += 1
            continue

        if node.get("relationshipType") == "hasAssociatedVulnerability":
            dropped_ids.add(node.get("spdxId"))
            stats.relationships_dropped += 1
            continue

        kept.append(node)

    # Otherwise None matches every relationship that omits "from".
    dropped_ids.discard(None)
    graph[:] = [n for n in kept if not _prune_refs(n, dropped_ids, stats)]
    for node in graph:
        if isinstance(node, dict):
            _redact_name(node, stats)
    return doc

def _is_dead(ref, dropped_ids):
    """A node the filter removed, or an alias URI naming a CVE.

    The second is never in dropped_ids: those vulnerabilities are owned by other
    documents, so the identifier in the URI is all this one has to go on.
    """
    return ref in dropped_ids or (isinstance(ref, str) and bool(CVE_RE.search(ref)))

def _prune_refs(node, dropped_ids, stats):
    """Drop dead targets; return whether the node is left relating nothing.

    Per target, not per node: a relationship naming a vulnerability alongside
    real files still describes those files.
    """
    if not isinstance(node, dict) or "to" not in node:
        return False

    if _is_dead(node.get("from"), dropped_ids):
        stats.relationships_dropped += 1
        return True

    targets = [t for t in _to_list(node["to"]) if not _is_dead(t, dropped_ids)]
    if not targets:
        stats.relationships_dropped += 1
        return True

    node["to"] = targets if isinstance(node["to"], list) else targets[0]
    return False

def _filter_spdx22(doc, stats):
    for package in doc.get("packages", []):
        if not isinstance(package, dict):
            continue
        # "CVEs fixed: <ids>", from get_patched_cves(). It sits on the package
        # itself, so the field goes and the package stays.
        if package.pop("sourceInfo", None) is not None:
            stats.fields_dropped += 1
        refs = package.get("externalRefs")
        if isinstance(refs, list):
            keep = [
                r for r in refs
                if not isinstance(r, dict) or r.get("referenceCategory") != "SECURITY"
            ]
            stats.fields_dropped += len(refs) - len(keep)
            package["externalRefs"] = keep
        _redact_name(package, stats)

    for key in ("files", "snippets"):
        for node in doc.get(key, []):
            if isinstance(node, dict):
                _redact_name(node, stats)
    return doc

def filter_document(doc, stats):
    """Strip the assessment from one parsed SPDX document, in place."""
    if "@graph" in doc:
        return _filter_graph(doc, stats)
    return _filter_spdx22(doc, stats)

def leaks(value, path="$"):
    """Where a CVE identifier still appears. Empty is the gate passing."""
    found = []
    if isinstance(value, dict):
        for key, item in value.items():
            found.extend(leaks(item, "%s.%s" % (path, key)))
    elif isinstance(value, list):
        for i, item in enumerate(value):
            found.extend(leaks(item, "%s[%d]" % (path, i)))
    elif isinstance(value, str) and CVE_RE.search(value):
        found.append("%s: %s" % (path, ", ".join(sorted(set(CVE_RE.findall(value))))))
    return found

def documents(root):
    """Every SPDX document under root, by real path.

    by-hash/, by-namespace/ and by-spdxid-hash/ mirror the arch directories in
    symlinks, so following them would filter each document three times.
    """
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames.sort()
        for name in sorted(filenames):
            path = os.path.join(dirpath, name)
            if name.endswith(".spdx.json"):
                yield path, os.path.islink(path)

def run(in_dir, out_dir, stats, warn):
    """Filter in_dir into out_dir, or check it in place when out_dir is None."""
    for path, is_link in documents(in_dir):
        if is_link:
            stats.symlinks_skipped += 1
            continue

        try:
            with open(path) as f:
                doc = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            stats.unreadable += 1
            warn("%s: unreadable: %s" % (path, e))
            continue

        stats.documents += 1
        if out_dir is not None:
            try:
                filter_document(doc, stats)
            except Exception as e:
                # Valid JSON of the wrong shape. Counted rather than raised, so
                # one bad file does not kill a 13,000-document run.
                stats.unreadable += 1
                warn("%s: not filterable: %s: %s" % (path, type(e).__name__, e))
                continue

        found = leaks(doc)
        if found:
            stats.leaked += 1
            for message in found[:5]:
                warn("%s: %s" % (path, message))
            continue

        if out_dir is not None:
            write_report(doc, os.path.join(out_dir, os.path.relpath(path, in_dir)),
                         indent=None)

def main():
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Filter SPDX documents down to a publishable inventory"
    )
    parser.add_argument("--in", dest="in_dir", required=True,
                        help="SPDX tree or directory, e.g. build/tmp/deploy/spdx/3.0.1 "
                             "or build/tmp/deploy/images/<machine>")
    parser.add_argument("-o", "--out",
                        help="write the filtered tree here")
    parser.add_argument("--check", action="store_true",
                        help="run the gate against --in as it stands, write nothing")
    args = parser.parse_args()

    if bool(args.out) == args.check:
        parser.error("pass either --out or --check")
    if not os.path.isdir(args.in_dir):
        parser.error("%s is not a directory" % args.in_dir)

    stats = Stats()
    run(args.in_dir, None if args.check else args.out, stats,
        lambda m: print(m, file=sys.stderr))

    if not stats.documents:
        print("no *.spdx.json under %s; nothing was filtered. SPDX documents "
              'need INHERIT += "create-spdx" and live under '
              "${DEPLOY_DIR}/spdx/<version>; the flattened per-image document "
              "is in ${DEPLOY_DIR}/images/<machine> and only exists if the "
              "image recipe was built." % args.in_dir, file=sys.stderr)
        return 1

    print("%s: %d documents%s" % (
        args.in_dir, stats.documents,
        "" if args.check else " -> " + args.out), file=sys.stderr)
    for key in ("nodes_dropped", "relationships_dropped", "fields_dropped",
                "names_redacted", "symlinks_skipped", "unreadable", "leaked"):
        if stats[key]:
            print("  %s: %d" % (key, stats[key]), file=sys.stderr)

    if stats.leaked:
        print("%d document(s) carry a CVE identifier after filtering; not "
              "publishable. The shape above is one this filter does not "
              "handle - teach it that shape rather than widening the gate."
              % stats.leaked, file=sys.stderr)
    if stats.unreadable:
        print("%d document(s) could not be read or filtered; the tree is "
              "incomplete. An interrupted build leaves truncated files behind."
              % stats.unreadable, file=sys.stderr)
    if stats.leaked or stats.unreadable:
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
