#!/usr/bin/env bash
# Stage one half of an add-on feed (docs/addon-feeds.md) from its
# multiconfig's deploy tree, ready to publish.
#
#   addon-feed-stage.sh --base <base deploy/rpm> --addon <addon deploy/rpm> \
#                       --role target|sdk --out <dir>
#
# Writes <out>/<arch_dir>/*.rpm with repodata in each arch dir, the shape the
# base feed's arch dirs have after `bitbake package-index`. The role picks the
# arch dirs: target takes every arch except the SDK ones, sdk takes
# *_avocadosdk, all_avocadosdk included. The target half must have packages;
# an add-on with no SDK packages gets an empty <out> for sdk, so both halves
# of every add-on always exist.
#
# The add-on carries only what the base feed does not:
#   - an RPM under the same file name as one in the base deploy tree is the
#     base package, rebuilt from the same sstate; it is left out, and must be
#     byte-identical ("drift" otherwise);
#   - any other RPM whose package name the base already ships, or that
#     obsoletes one, would replace that base package on a device ("shadow").
# Either fails the stage, and <out> is left as it was, so an add-on can never
# change what a base package is.
#
# Package names come from repodata (createrepo_c), not rpm, which build images
# do not all have.
set -euo pipefail

usage() {
  echo "usage: $0 --base DIR --addon DIR --role target|sdk --out DIR" >&2
  exit 2
}

BASE='' ADDON='' ROLE='' OUT=''
while [ $# -gt 0 ]; do
  case $1 in
    --base)
      BASE=$2
      shift 2
      ;;
    --addon)
      ADDON=$2
      shift 2
      ;;
    --role)
      ROLE=$2
      shift 2
      ;;
    --out)
      OUT=$2
      shift 2
      ;;
    *) usage ;;
  esac
done
[ -n "$BASE" ] && [ -n "$ADDON" ] && [ -n "$OUT" ] || usage
case $ROLE in target | sdk) ;; *) usage ;; esac
BASE=${BASE%/} ADDON=${ADDON%/} OUT=${OUT%/}
for tool in createrepo_c python3; do
  command -v "$tool" >/dev/null || {
    echo "error: $tool is required" >&2
    exit 1
  }
done
[ -d "$BASE" ] || {
  echo "error: base deploy tree $BASE does not exist" >&2
  exit 1
}
if [ ! -d "$ADDON" ]; then
  if [ "$ROLE" = target ]; then
    echo "error: add-on deploy tree $ADDON does not exist; was its multiconfig built?" >&2
    exit 1
  fi
fi

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

# <tree> -> lines "<path relative to tree>\t<name>\t<obsoleted names, space-separated>"
packages() {
  local tree=$1 md=$2
  mkdir -p "$md"
  if ! createrepo_c -q --general-compress-type=gz --excludes 'repodata/*' \
    --outputdir "$md" "$tree" 2>"$md.err"; then
    echo "error: cannot index $tree:" >&2
    cat "$md.err" >&2
    exit 1
  fi
  python3 - "$md" <<'PY'
import glob, gzip, sys
import xml.etree.ElementTree as ET
ns = {"c": "http://linux.duke.edu/metadata/common", "rpm": "http://linux.duke.edu/metadata/rpm"}
primary = glob.glob(f"{sys.argv[1]}/repodata/*primary.xml.gz")[0]
for pkg in ET.parse(gzip.open(primary)).getroot().findall("c:package", ns):
    obsoletes = " ".join(e.get("name") for e in pkg.findall("c:format/rpm:obsoletes/rpm:entry", ns))
    print(f"{pkg.find('c:location', ns).get('href')}\t{pkg.find('c:name', ns).text}\t{obsoletes}")
PY
}

in_role() {
  case $1 in
    repodata | sdk_provides_dummy*) return 1 ;;
    *_avocadosdk) [ "$ROLE" = sdk ] ;;
    *) [ "$ROLE" = target ] ;;
  esac
}

packages "$BASE" "$work/base-md" | cut -f2 | sort -u >"$work/base-names"

mkdir -p "$work/out"
drift=0 shadow=0 staged=0
if [ -d "$ADDON" ]; then
  packages "$ADDON" "$work/addon-md" >"$work/addon-pkgs"
  while IFS=$'\t' read -r rel name obsoletes; do
    arch_dir=${rel%%/*}
    if [ "$arch_dir" = "$rel" ]; then
      echo "error: $ADDON/$rel is not in an arch dir" >&2
      exit 1
    fi
    in_role "$arch_dir" || continue
    if [ -e "$BASE/$rel" ]; then
      if ! cmp -s "$ADDON/$rel" "$BASE/$rel"; then
        echo "drift: $rel differs from the base build's copy" >&2
        drift=$((drift + 1))
      fi
      continue
    fi
    for n in $name $obsoletes; do
      if grep -qxF -- "$n" "$work/base-names"; then
        echo "shadow: $rel would replace base package '$n'" >&2
        shadow=$((shadow + 1))
        continue 2
      fi
    done
    mkdir -p "$work/out/$arch_dir"
    cp -p "$ADDON/$rel" "$work/out/$arch_dir/"
    staged=$((staged + 1))
  done <"$work/addon-pkgs"
fi

if [ $drift -gt 0 ] || [ $shadow -gt 0 ]; then
  echo "error: $drift drifted and $shadow shadowing package(s); add-on $ROLE half not staged" >&2
  exit 1
fi
if [ "$ROLE" = target ] && [ $staged -eq 0 ]; then
  echo "error: the add-on's target half is empty; nothing in $ADDON is the add-on's own" >&2
  exit 1
fi

for d in "$work/out"/*/; do
  [ -d "$d" ] && createrepo_c -q --general-compress-type=gz "$d"
done
mkdir -p "$(dirname "$OUT")"
rm -rf "$OUT"
mv "$work/out" "$OUT"
echo "staged $staged package(s) for the add-on $ROLE half in $OUT"
