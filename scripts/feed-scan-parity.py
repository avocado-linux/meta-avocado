#!/usr/bin/env python3
"""Compare the task signatures two kas stacks dumped with `bitbake -S none`.

Run by scripts/feed-scan-parity.sh.

  compare <dir>: reads <dir>/feed and <dir>/scan. Exit 1 when a compared
    task's hash differs, 0 when none does, 2 when the dumps cannot be read.
    Writes <dir>/examples.json for explain.
  explain --bitbake <checkout> <dir>: bitbake's own sigdata diff for a few
    of the differing tasks. Diagnostics only: always exits 0.
"""

import argparse
import concurrent.futures
import json
import os
import re
import subprocess
import sys
import traceback
from collections import Counter, defaultdict

# The sstate tasks the scan takes from the feed build. A difference in any
# other task is listed but does not fail the check.
COMPARED = {
    "do_package_write_rpm",
    "do_package",
    "do_packagedata",
    "do_package_qa",
    "do_populate_sysroot",
    "do_populate_lic",
    "do_deploy",
    "do_deploy_source_date_epoch",
    "do_image_complete",
}
COMPARED_RE = re.compile(r"^do_create_\w*spdx$")

# Recipes and tasks the scan adds on purpose. Only matters where one is in
# both graphs: a task only the scan runs is never compared.
EXCLUDED_PN = {
    # The NVD database the cve-check class reads, the kernel CNA data the
    # kernel filter reads (both refreshed on a timer, not pinned), and the
    # report.
    "cve-update-nvd2-native": "scan database, refreshed on a timer",
    "avocado-cve-kernel-vulns-native": "kernel CNA data, refreshed on a timer",
    "avocado-cve-report": "the report itself",
}
EXCLUDED_TASKS = {
    "do_cve_check": "the scan's own task",
}

SIG_RE = re.compile(r"^(?P<ver>.*)\.(?P<task>do_\w+)\.sigdata\.(?P<hash>[0-9a-f]+)$")
EXAMPLES = "examples.json"


class DumpError(Exception):
    pass


def index(root):
    """(tmpdir, arch, pn, task) -> (version, hash, path) for every dumped signature."""
    out = {}
    for dirpath, _, files in os.walk(root):
        rel = os.path.relpath(dirpath, root).split(os.sep)
        if len(rel) != 3:
            continue
        for f in files:
            m = SIG_RE.match(f)
            if not m:
                continue
            key = (rel[0], rel[1], rel[2], m["task"])
            if key in out:
                raise DumpError(f"two signatures for {'/'.join(key)} in {root}; stale stamps?")
            out[key] = (m["ver"], m["hash"], os.path.join(dirpath, f))
    return out


def load(path):
    raw = subprocess.run(["zstd", "-dcq", path], check=True, capture_output=True).stdout
    return json.loads(raw)


def nostamp(sig):
    return str(sig.get("taint", "")).startswith("nostamp:")


def compared(key):
    task = key[3]
    return (task in COMPARED or COMPARED_RE.match(task)) and key[2] not in EXCLUDED_PN \
        and task not in EXCLUDED_TASKS


def label(key):
    tmp, arch, pn, task = key
    mc = "" if tmp == "tmp" else f"[{tmp}] "
    return f"{mc}{pn}:{task}"


def why(a, b):
    """What differs in the task itself, or None when only a dependency's hash does."""
    out = []
    va, vb = a.get("varvals", {}), b.get("varvals", {})
    out += sorted(k for k in set(va) | set(vb) if va.get(k) != vb.get(k))
    if a.get("file_checksum_values") != b.get("file_checksum_values"):
        out.append("(file checksums)")
    da, db = set(a.get("runtaskdeps", [])), set(b.get("runtaskdeps", []))
    if da != db:
        out.append("(task dependencies)")
    if a.get("taint") != b.get("taint"):
        out.append("(taint)")
    if not out and a.get("basehash") != b.get("basehash"):
        out.append("(basehash)")
    return tuple(out) or None


def from_nostamp(differ, sigs, feed, scan):
    """The differing tasks a nostamp task explains on its own.

    A nostamp task gets a random taint on every parse, so its hash never
    matches across the two parses, and every task depending on it inherits
    that. None of them can come from sstate in any build, so they are not
    drift. Only a task nostamp in both stacks is a seed: one the scan alone
    makes nostamp is drift. A task counts only when its own inputs are
    identical and every dependency whose hash differs is itself explained
    this way; anything that cannot be traced is left in, to be reported.
    """
    # Identical tasks in two multiconfigs share a hash, so a hash alone does
    # not name a task.
    def byhash(idx):
        out = defaultdict(set)
        for k, (_, h, _) in idx.items():
            out[h].add(k)
        return out
    fh, sh = byhash(feed), byhash(scan)
    differ_set = set(differ)
    seeds, deps = set(), {}
    for k in differ:
        a, b = sigs[k]
        if nostamp(a) and nostamp(b):
            seeds.add(k)
            continue
        if feed[k][0] != scan[k][0] or why(a, b):
            continue
        ha, hb = a.get("runtaskhashes", {}), b.get("runtaskhashes", {})
        ds = []
        for d in set(ha) | set(hb):
            if ha.get(d) == hb.get(d):
                continue
            pn, task = d.split(":")[-2:]
            cands = {c for c in fh.get(ha.get(d), set()) & sh.get(hb.get(d), set())
                     if c[2] == pn and c[3] == task}
            # Every multiconfig here sets TMPDIR to tmp-<mc>.
            tmp = "tmp-" + d.split(":")[1] if d.startswith("mc:") else "tmp"
            cands = {c for c in cands if c[0] == tmp} or cands
            if not cands or not cands <= differ_set:
                ds = None
                break
            ds += cands
        if ds:
            deps[k] = ds
    # Iterate to a fixpoint rather than recurse: dependency chains run deep.
    explained = set(seeds)
    grew = True
    while grew:
        grew = False
        for k, ds in deps.items():
            if k not in explained and all(d in explained for d in ds):
                explained.add(k)
                grew = True
    return seeds, explained


def compare(args):
    feed = index(os.path.join(args.dir, "feed"))
    scan = index(os.path.join(args.dir, "scan"))
    if not feed or not scan:
        raise DumpError("no signatures dumped")
    both = sorted(set(feed) & set(scan))
    differ = [k for k in both if feed[k][1] != scan[k][1] or feed[k][0] != scan[k][0]]

    with concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
        sigs = dict(zip(differ, pool.map(lambda k: (load(feed[k][2]), load(scan[k][2])), differ)))

    seeds, skipped = from_nostamp(differ, sigs, feed, scan)
    differ = [k for k in differ if k not in skipped]

    # A task whose stamp directory (PACKAGE_ARCH) differs is in neither
    # list above, yet still rebuilds. Pair one-sided tasks by multiconfig,
    # recipe and task where that is unique on both sides.
    def loose(keys):
        n = Counter((k[0], k[2], k[3]) for k in keys)
        return {(k[0], k[2], k[3]): k for k in keys if n[(k[0], k[2], k[3])] == 1}
    lf, ls = loose(set(feed) - set(scan)), loose(set(scan) - set(feed))
    moved = [(lf[t], ls[t]) for t in sorted(set(lf) & set(ls))]
    moved_keys = {k for pair in moved for k in pair}

    def reusable(fk, sk):
        # do_populate_lic's sstate name does not carry the package arch, and
        # a task nostamp in both stacks never had sstate to lose.
        if fk[3] == "do_populate_lic" and feed[fk][:2] == scan[sk][:2]:
            return True
        return nostamp(load(feed[fk][2])) and nostamp(load(scan[sk][2]))
    moved = [(fk, sk) for fk, sk in moved if not reusable(fk, sk)]

    drift = [k for k in differ if compared(k)] + [sk for fk, sk in moved if compared(fk)]
    other = [k for k in differ if not compared(k)] + [sk for fk, sk in moved if not compared(fk)]
    roots = defaultdict(list)
    for k in differ:
        a, b = sigs[k]
        if feed[k][0] != scan[k][0]:
            roots[(f"(version {feed[k][0]} -> {scan[k][0]})",)].append(k)
            continue
        w = why(a, b)
        if w:
            roots[w].append(k)
    for fk, sk in moved:
        roots[(f"(package arch {fk[1]} -> {sk[1]})",)].append(sk)
    ranked = sorted(roots.items(), key=lambda i: (-len(i[1]), i[0]))
    for _, ks in ranked:
        ks.sort(key=lambda k: (not compared(k), k))

    only_feed = Counter(k[3] for k in set(feed) - set(scan) - moved_keys)
    only_scan = sorted({k[2] for k in set(scan) - set(feed) - moved_keys})

    lines = []
    p = lines.append
    if drift:
        p("## Feed/scan parity: the CVE scan would rebuild work the feed build cached")
    else:
        p("## Feed/scan parity: no difference in the compared tasks")
    p("")
    p(f"- Tasks in both stacks: {len(both)} (feed {len(feed)}, scan {len(scan)})")
    p(f"- Compared tasks that differ: **{len(drift)}**")
    p(f"- Other tasks that differ (not failed on): {len(other)}")
    p(f"- Skipped, a nostamp task or only downstream of one: {len(skipped)}"
      + (f" (nostamp: {', '.join(label(k) for k in sorted(seeds)[:6])}{', ...' if len(seeds) > 6 else ''})"
         if seeds else ""))
    p(f"- Recipes only the scan runs: {len(only_scan)}"
      + (f" ({', '.join(only_scan[:12])}{', ...' if len(only_scan) > 12 else ''})" if only_scan else ""))
    if only_feed:
        p(f"- Tasks only the feed runs: {sum(only_feed.values())}")
    if ranked:
        p("")
        p("### Where the differences start")
        p("")
        p("Tasks whose own inputs differ, grouped by what differs. Every other differing task only")
        p("inherits a changed dependency hash.")
        p("")
        p("| Differs | Tasks | Example |")
        p("|---|---|---|")
        for w, ks in ranked:
            p(f"| `{', '.join(w)}` | {len(ks)} | `{label(ks[0])}` |")
    if drift:
        p("")
        p("### Compared tasks that differ")
        p("")
        for t, n in sorted(Counter(k[3] for k in drift).items(), key=lambda i: (-i[1], i[0])):
            p(f"- `{t}`: {n}")
    print("\n".join(lines))
    # Both writes are reporting only; neither may change the exit code.
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    try:
        if summary:
            with open(summary, "a") as f:
                f.write("\n".join(lines) + "\n")
    except OSError as e:
        print(f"feed-scan-parity: could not write the step summary: {e}", file=sys.stderr)
    feed_of = {sk: fk for fk, sk in moved}
    examples = [{"label": label(ks[0]), "differs": ", ".join(w),
                 "feed": feed[feed_of.get(ks[0], ks[0])][2], "scan": scan[ks[0]][2]}
                for w, ks in ranked[: args.examples]]
    try:
        with open(os.path.join(args.dir, EXAMPLES), "w") as f:
            json.dump(examples, f, indent=1)
    except OSError as e:
        print(f"feed-scan-parity: could not write {EXAMPLES}: {e}", file=sys.stderr)

    return 1 if drift else 0


def explain(args):
    path = os.path.join(args.dir, EXAMPLES)
    if not os.path.exists(path):
        print("nothing to explain")
        return 0
    with open(path) as f:
        examples = json.load(f)
    if not examples:
        print("nothing to explain")
        return 0

    # The comparison bitbake-diffsigs prints, without its tinfoil setup: that
    # needs a configured build only to look up dependencies' sigdata, which
    # this does not follow.
    sys.path.insert(0, os.path.join(args.bitbake, "lib"))
    import bb.siggen

    lines = ["", "### What bitbake-diffsigs says (feed -> scan)", ""]
    for ex in examples:
        print(f"\n=== bitbake-diffsigs {ex['label']} (feed -> scan)")
        try:
            out = "\n".join(bb.siggen.compare_sigfiles(ex["feed"], ex["scan"])).splitlines()
        except Exception:
            out = ["could not compare:"] + traceback.format_exc().splitlines()
        if len(out) > args.lines:
            out = out[: args.lines] + ["..."]
        print("\n".join(out))
        lines += [f"<details><summary><code>{ex['label']}</code>: {ex['differs']}</summary>", "",
                  "```", *out, "```", "", "</details>", ""]
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write("\n".join(lines) + "\n")
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("compare")
    c.add_argument("--examples", type=int, default=3)
    c.add_argument("dir")
    e = sub.add_parser("explain")
    e.add_argument("--bitbake", required=True)
    e.add_argument("--lines", type=int, default=60)
    e.add_argument("dir")
    args = ap.parse_args()

    if args.cmd == "explain":
        try:
            return explain(args)
        except Exception:
            traceback.print_exc()
            return 0
    # Exit 1 is reserved for a real difference; anything that stops the
    # comparison is 2.
    try:
        return compare(args)
    except Exception as e:
        print(f"feed-scan-parity: could not compare: {e}", file=sys.stderr)
        traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())
