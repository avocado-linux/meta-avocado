#!/usr/bin/env bash
# Publish an add-on feed (docs/addon-feeds.md) into a local dev repo, beside
# the base feed dev-sync-packages.sh wrote:
#
#   <repo>/releases/<codename>/<id>/target/<target>-<addon>/
#   <repo>/releases/<codename>/<id>/sdk/<target>-<addon>/
#
# and list both in that channel's targets.json, which is how avocado-cli
# finds the add-ons a target has. Selection and the guard against shadowing a
# base package are scripts/addon-feed-stage.sh, which the production build
# runs too.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
    cat << EOF
Usage: $0 -r REPO_DIR -d CODENAME -i ID -b BUILD_DIR -a ADDON TARGET

    -r  dev repo directory (the one dev-sync-packages.sh wrote)
    -d  distro codename, e.g. 2026/next
    -i  release id, e.g. dev
    -b  build directory, e.g. build-raspberrypi5
    -a  add-on feed name, which is also its multiconfig's name, e.g. ros2-jazzy
EOF
}

REPO_DIR='' CODENAME='' RELEASE_ID='' BUILD_DIR='' ADDON=''
while getopts "r:d:i:b:a:h" o; do
    case $o in
        r) REPO_DIR=$OPTARG ;; d) CODENAME=$OPTARG ;; i) RELEASE_ID=$OPTARG ;;
        b) BUILD_DIR=$OPTARG ;; a) ADDON=$OPTARG ;;
        *) usage; exit 1 ;;
    esac
done
shift $((OPTIND - 1))
TARGET=${1:-}
for v in REPO_DIR CODENAME RELEASE_ID BUILD_DIR ADDON TARGET; do
    [ -n "${!v}" ] || { usage; exit 1; }
done

OUT=$REPO_DIR/releases/$CODENAME/$RELEASE_ID
for role in target sdk; do
    dest=$OUT/$role/$TARGET-$ADDON
    "$SCRIPT_DIR/addon-feed-stage.sh" --base "$BUILD_DIR/build/tmp/deploy/rpm" \
        --addon "$BUILD_DIR/build/tmp-$ADDON/deploy/rpm" --role "$role" --out "$dest"
    # One repo per root, like the base feed's per-machine repos.
    createrepo_c -q --general-compress-type=gz "$dest"
done

# The target's fragment too: dev-package-extensions.sh rebuilds targets.json
# from the fragments, and would otherwise drop the add-on.
python3 - "$OUT/targets.json" "$REPO_DIR/staging/$RELEASE_ID/fragments" "$TARGET" "$ADDON" << 'PY'
import glob, json, os, sys
path, fragments, target, addon = sys.argv[1:]
add = [f"target/{target}-{addon}", f"sdk/{target}-{addon}"]

def extend(file, seed):
    doc = seed
    if os.path.exists(file):
        with open(file) as f:
            doc = json.load(f)
    repos = doc.setdefault(target, [])
    repos += [r for r in add if r not in repos]
    with open(file, "w") as f:
        json.dump(doc, f, indent=2, sort_keys=True)

frag = os.path.join(fragments, f"{target}-fragment.json")
if os.path.exists(frag):
    extend(frag, {})
seed = {}
for f in sorted(glob.glob(os.path.join(fragments, "*-fragment.json"))):
    with open(f) as fh:
        seed.update(json.load(fh))
extend(path, seed)
PY
echo "add-on '$ADDON' published for $TARGET under $OUT"
