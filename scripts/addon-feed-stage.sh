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
# *_avocadosdk, all_avocadosdk included. An add-on with nothing for a role
# still gets <out>, empty, so both halves of every add-on always exist.
#
# The add-on carries only what the base feed does not:
#   - an RPM under the same file name as one in the base deploy tree is the
#     base package, rebuilt from the same sstate; it is left out, and must be
#     byte-identical ("drift" otherwise);
#   - any other RPM whose package name the base already ships would replace
#     that base package on a device ("shadow").
# Either fails the stage, and nothing is written, so an add-on can never
# change what a base package is.
set -euo pipefail

usage() {
    echo "usage: $0 --base DIR --addon DIR --role target|sdk --out DIR" >&2
    exit 2
}

BASE='' ADDON='' ROLE='' OUT=''
while [ $# -gt 0 ]; do
    case $1 in
        --base) BASE=$2; shift 2 ;;
        --addon) ADDON=$2; shift 2 ;;
        --role) ROLE=$2; shift 2 ;;
        --out) OUT=$2; shift 2 ;;
        *) usage ;;
    esac
done
[ -n "$BASE" ] && [ -n "$ADDON" ] && [ -n "$OUT" ] || usage
case $ROLE in target|sdk) ;; *) usage ;; esac
[ -d "$BASE" ] || { echo "error: base deploy tree $BASE does not exist" >&2; exit 1; }

in_role() {
    case $1 in
        repodata|sdk_provides_dummy*) return 1 ;;
        *_avocadosdk) [ "$ROLE" = sdk ] ;;
        *) [ "$ROLE" = target ] ;;
    esac
}

names_of() { xargs -0 -r rpm -qp --nosignature --qf '%{NAME}\n' 2>/dev/null; }

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
find "$BASE" -name '*.rpm' -print0 | names_of | sort -u > "$work/base-names"

rm -rf "$OUT"
mkdir -p "$work/out"
drift=0 shadow=0 staged=0
# No add-on deploy tree: the multiconfig built nothing for this role.
if [ -d "$ADDON" ]; then
    while IFS= read -r -d '' rpm; do
        rel=${rpm#"$ADDON"/}
        arch_dir=${rel%%/*}
        in_role "$arch_dir" || continue
        if [ -e "$BASE/$rel" ]; then
            if ! cmp -s "$rpm" "$BASE/$rel"; then
                echo "drift: $rel differs from the base build's copy" >&2
                drift=$((drift + 1))
            fi
            continue
        fi
        name=$(rpm -qp --nosignature --qf '%{NAME}' "$rpm" 2>/dev/null)
        if grep -qxF -- "$name" "$work/base-names"; then
            echo "shadow: $rel would replace base package '$name'" >&2
            shadow=$((shadow + 1))
            continue
        fi
        mkdir -p "$work/out/$arch_dir"
        cp -p "$rpm" "$work/out/$arch_dir/"
        staged=$((staged + 1))
    done < <(find "$ADDON" -name '*.rpm' -print0)
fi

if [ $drift -gt 0 ] || [ $shadow -gt 0 ]; then
    echo "error: $drift drifted and $shadow shadowing package(s); add-on $ROLE half not staged" >&2
    exit 1
fi

for d in "$work/out"/*/; do
    [ -d "$d" ] && createrepo_c -q --general-compress-type=gz "$d"
done
mkdir -p "$(dirname "$OUT")"
mv "$work/out" "$OUT"
echo "staged $staged package(s) for the add-on $ROLE half in $OUT"
