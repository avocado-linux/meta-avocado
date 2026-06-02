#!/usr/bin/env python3
"""Local content-addressed-pool render — the dev mirror of the production render.

Production renders the public 2026 feed with `render_pool.py` (avocado-package),
reading a Pulp publication and doing S3->S3 pooling. Locally we don't run Pulp —
that's overkill — but the dev repo must serve the SAME shape so `avocado-cli` and
dnf exercise the real layout:

    <channel-root>/_pkgs/<aa>/<sha256>.rpm          # every package ONCE, content-addressed
    <channel-root>/<subpath>/repodata/              # per-repo metadata, gzip
        primary.xml  ->  location_href  ../../_pkgs/<aa>/<sha256>.rpm

This is a self-contained copy of just the chunks we need from render_pool.py
(pool the bytes, rewrite primary's location_href to the pool at the right depth,
regenerate repomd) — stdlib only, filesystem source + sink, no Pulp/S3/boto3.

Per invocation it renders ONE repo (one repodata) from a staged RPM tree:
  - SOURCE: `createrepo_c` over <staged-root> (recurses arch subdirs) is our
    publication, replacing render_pool's fetch-from-Pulp.
  - POOL  : copy each staged RPM -> <channel-root>/_pkgs/<aa>/<sha>.rpm, replacing
    render_pool's S3->S3 copy_object.
  - PUBLISH: write the rewritten repodata to <channel-root>/<subpath>/repodata/,
    replacing render_pool's `aws s3 sync`.

The pool ref depth matches render_pool: `../` * len(subpath segments) + `_pkgs`,
so `target/<machine>` and `sdk/<machine>` (2 segments) both resolve to
<channel-root>/_pkgs.

Usage:
  render-pool-local.py --staged <dir> --channel-root <dir> --subpath <target/qemuarm64>
"""
import argparse
import gzip
import hashlib
import os
import shutil
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET

REPO_NS = "http://linux.duke.edu/metadata/repo"
COMMON_NS = "http://linux.duke.edu/metadata/common"
RPM_NS = "http://linux.duke.edu/metadata/rpm"
NS = {"repo": REPO_NS, "common": COMMON_NS}

# Preserve the canonical namespace prefixes on re-serialization (no ns0:).
ET.register_namespace("", COMMON_NS)
ET.register_namespace("rpm", RPM_NS)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def createrepo_source(staged_root, work):
    """Run createrepo_c over the staged tree (recursing arch subdirs) to produce our
    source repodata, gzip-compressed so the filelists/other docs match production.
    Returns (repomd_path, primary_path, datas) where datas maps type->href."""
    subprocess.run(
        ["createrepo_c", "--general-compress-type", "gz", "--outputdir", work, staged_root],
        check=True,
    )
    repomd_path = os.path.join(work, "repodata", "repomd.xml")
    repomd = ET.parse(repomd_path)
    datas = {}
    for d in repomd.getroot().findall("repo:data", NS):
        href = d.find("repo:location", NS).get("href")
        datas[d.get("type")] = href
    primary_path = os.path.join(work, datas["primary"])
    return repomd_path, primary_path, datas


def pool_and_rewrite(primary_path, staged_root, pool_dir, pool_rel):
    """Copy every staged RPM into the content-addressed pool and rewrite each
    package's location_href to point at the pool. Mutates the parsed primary tree.
    Returns (primary_tree, package_count)."""
    if primary_path.endswith(".gz"):
        with gzip.open(primary_path) as f:
            tree = ET.parse(f)
    else:
        tree = ET.parse(primary_path)
    root = tree.getroot()
    pkgs = root.findall("common:package", NS)

    pooled = 0
    for p in pkgs:
        # pkgid checksum == the RPM file's sha256 (createrepo_c sha256 default).
        sha = p.find("common:checksum", NS).text
        loc = p.find("common:location", NS)
        orig_href = loc.get("href")  # e.g. cortexa57/foo.rpm, relative to staged_root

        src_rpm = os.path.join(staged_root, orig_href)
        aa = sha[:2]
        dst_rpm = os.path.join(pool_dir, aa, f"{sha}.rpm")
        if not os.path.exists(dst_rpm):
            os.makedirs(os.path.dirname(dst_rpm), exist_ok=True)
            # copy2 preserves mtime; the pool is content-addressed so this is a
            # one-time write per sha (skipped above when already present).
            shutil.copy2(src_rpm, dst_rpm)
            pooled += 1

        loc.set("href", f"{pool_rel}/{aa}/{sha}.rpm")

    return tree, len(pkgs), pooled


def write_repodata(repomd_path, primary_tree, datas, src_work, out_repodata):
    """Re-serialize the rewritten primary, regenerate repomd's primary entry, and
    publish the repodata (rewritten primary + verbatim filelists/other + repomd) to
    out_repodata. Mirrors render_pool.write_repodata's regen, sans S3."""
    os.makedirs(out_repodata, exist_ok=True)

    # Re-serialize the rewritten primary and gzip it (matches production gzip).
    raw = ET.tostring(primary_tree.getroot(), xml_declaration=True, encoding="UTF-8")
    open_sha = hashlib.sha256(raw).hexdigest()
    tmp_gz = os.path.join(out_repodata, "primary.xml.gz.tmp")
    with gzip.open(tmp_gz, "wb", compresslevel=9) as g:
        g.write(raw)
    comp_sha = sha256_file(tmp_gz)
    comp_size = os.path.getsize(tmp_gz)
    new_primary = f"{comp_sha}-primary.xml.gz"
    os.replace(tmp_gz, os.path.join(out_repodata, new_primary))

    # Copy filelists/other verbatim (no location_href to rewrite).
    for t in ("filelists", "other"):
        if t in datas:
            shutil.copy2(os.path.join(src_work, datas[t]),
                         os.path.join(out_repodata, os.path.basename(datas[t])))

    # Update repomd's primary <data> to the rewritten file, then write it out.
    repomd = ET.parse(repomd_path)
    for d in repomd.getroot().findall("repo:data", NS):
        if d.get("type") != "primary":
            continue
        d.find("repo:checksum", NS).text = comp_sha
        oc = d.find("repo:open-checksum", NS)
        if oc is not None:
            oc.text = open_sha
        d.find("repo:location", NS).set("href", f"repodata/{new_primary}")
        sz = d.find("repo:size", NS)
        if sz is not None:
            sz.text = str(comp_size)
        osz = d.find("repo:open-size", NS)
        if osz is not None:
            osz.text = str(len(raw))
        ts = d.find("repo:timestamp", NS)
        if ts is not None:
            ts.text = str(int(os.path.getmtime(os.path.join(out_repodata, new_primary))))
    ET.register_namespace("", REPO_NS)
    ET.register_namespace("rpm", RPM_NS)
    repomd.write(os.path.join(out_repodata, "repomd.xml"),
                 xml_declaration=True, encoding="UTF-8")
    # Re-register common as default for any subsequent primary parse in-process.
    ET.register_namespace("", COMMON_NS)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--staged", required=True,
                    help="staged RPM tree for this repo (may contain arch subdirs)")
    ap.add_argument("--channel-root", required=True,
                    help="served channel root; _pkgs/ and <subpath>/ live under here")
    ap.add_argument("--subpath", required=True,
                    help="repo subpath under the channel root, e.g. target/qemuarm64")
    a = ap.parse_args()

    if not os.path.isdir(a.staged):
        raise SystemExit(f"staged dir not found: {a.staged}")
    if not any(f.endswith(".rpm") for f in _walk_files(a.staged)):
        print(f"render-pool-local: no RPMs under {a.staged}, skipping {a.subpath}")
        return

    subpath = a.subpath.strip("/")
    depth = len(subpath.split("/"))
    pool_rel = "../" * depth + "_pkgs"
    pool_dir = os.path.join(a.channel_root, "_pkgs")
    out_repodata = os.path.join(a.channel_root, subpath, "repodata")

    with tempfile.TemporaryDirectory(prefix="render-pool-local.") as work:
        repomd_path, primary_path, datas = createrepo_source(a.staged, work)
        primary_tree, total, pooled = pool_and_rewrite(
            primary_path, a.staged, pool_dir, pool_rel)
        write_repodata(repomd_path, primary_tree, datas, work, out_repodata)

    print(f"render-pool-local: {subpath} -> {out_repodata}")
    print(f"  packages: {total} ({pooled} newly pooled into {pool_dir}, "
          f"href -> {pool_rel}/<aa>/<sha>.rpm)")


def _walk_files(root):
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            yield f


if __name__ == "__main__":
    main()
