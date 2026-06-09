#!/usr/bin/env bash
#
# dev-repo.sh — one-shot developer helper to (re)populate and serve a local
# package feed for one or more targets.
#
# It wraps the lower-level scripts into a single memorable command:
#
#     ./scripts/dev-repo.sh <year> <target> [target2 ...]
#
# e.g.  ./scripts/dev-repo.sh 2026 imx8mp-evk
#
# which expands to: sync packages + package extensions for the target into
# <repo-root>/_repo under the 2026/edge feed, then (re)start the repo server.
#
# By default it is INCREMENTAL: it reuses a stable release id ("dev") so re-runs
# overwrite in place instead of piling up timestamped releases — no need to wipe
# the dir between builds. Pass --clean to reset just the target(s) you are
# working on (other targets sharing the same _repo are left untouched).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# --- Defaults -----------------------------------------------------------------
DEFAULT_CHANNEL="edge"
DEFAULT_REPO_DIR="$REPO_ROOT/_repo"
DEFAULT_PORT="8080"
# Stable release id so re-runs overwrite in place instead of accumulating
# timestamped release dirs (this is what removes the need to rm the repo dir).
DEFAULT_RELEASE_ID="dev"

# Autodetect the broken-out extensions repos: $AVOCADO_EXTENSIONS_DIR wins,
# otherwise the conventional sibling checkout next to this repo root.
DEFAULT_EXTENSIONS_DIR=""
if [ -n "${AVOCADO_EXTENSIONS_DIR:-}" ]; then
    DEFAULT_EXTENSIONS_DIR="$AVOCADO_EXTENSIONS_DIR"
elif [ -d "$REPO_ROOT/../extensions" ]; then
    DEFAULT_EXTENSIONS_DIR="$(cd "$REPO_ROOT/../extensions" && pwd)"
fi

usage() {
    cat << EOF
Usage: $0 [OPTIONS] <year> <target> [target2 ...]

(Re)populate and serve a local package feed for one or more targets, then
(re)start the repo server. Collapses dev-build.sh + dev-start-repo.sh into one
command.

Arguments:
    year                Feed year / release (e.g. 2026). Combined with the
                        channel to form the distro codename <year>/<channel>.
    target              One or more target names (e.g. imx8mp-evk).

Options:
    -c, --channel CHAN      Feed channel (default: $DEFAULT_CHANNEL)
    -r, --repo-dir DIR      Repository directory (default: <repo-root>/_repo)
    -E, --extensions-dir D  Combined extensions dir (bsp-*/ext-* repos).
                            Default: \$AVOCADO_EXTENSIONS_DIR or the sibling
                            ../extensions checkout.
    -p, --port PORT         Repo server port (default: $DEFAULT_PORT)
    -i, --release-id ID     Release id under the feed (default: $DEFAULT_RELEASE_ID)
    --build-ext             Build extensions before packaging (default: package only)
    --clean                 Reset the named target(s) before syncing. Removes
                            ONLY the per-target dirs (target/<t>, target/<t>-ext,
                            sdk/<t> under packages/ and releases/) plus the
                            staging fragment. Shared arch pools (noarch,
                            cortexa53_crypto, ...), the content-addressed _pkgs
                            pool, and other targets are left intact.
    --no-serve              Don't (re)start the repo server when done.
    -h, --help              Show this help message.

Examples:
    $0 2026 imx8mp-evk                  # incremental sync + serve
    $0 --clean 2026 imx8mp-evk          # reset just imx8mp-evk, then sync + serve
    $0 2026 imx8mp-evk raspberrypi5     # multiple targets into one feed
    $0 -c stable 2026 imx8mp-evk        # 2026/stable channel
    $0 --build-ext 2026 imx8mp-evk      # build extensions, not just package

For a full wipe of everything (all targets, content pool included), just
'rm -rf <repo-dir>' — that is the only thing this script deliberately won't do.
EOF
}

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

# Remove the dirs that belong exclusively to a single target, leaving shared
# pools and sibling targets alone. Named arch dirs (target/<target>, sdk/<target>)
# are guaranteed target-exclusive; shared tunes (noarch, cortexa53_crypto) and
# the _pkgs content pool are intentionally preserved and self-heal on re-sync.
clean_target() {
    local target="$1"
    local pkgs="$REPO_DIR/packages/$CODENAME"
    local rel="$REPO_DIR/releases/$CODENAME/$RELEASE_ID"
    local frag="$REPO_DIR/staging/$RELEASE_ID/fragments/$target-fragment.json"
    local count=0
    local d
    for d in \
        "$pkgs/target/$target" "$pkgs/target/$target-ext" "$pkgs/sdk/$target" \
        "$rel/target/$target" "$rel/target/$target-ext" "$rel/sdk/$target"; do
        if [ -d "$d" ]; then
            rm -rf "$d"
            count=$((count + 1))
        fi
    done
    if [ -f "$frag" ]; then
        rm -f "$frag"
        count=$((count + 1))
    fi
    log "  ✓ Reset $count target-scoped path(s) for '$target' (shared pools left intact)"
}

# --- Parse arguments ----------------------------------------------------------
CHANNEL="$DEFAULT_CHANNEL"
REPO_DIR="$DEFAULT_REPO_DIR"
EXTENSIONS_DIR="$DEFAULT_EXTENSIONS_DIR"
PORT="$DEFAULT_PORT"
RELEASE_ID="$DEFAULT_RELEASE_ID"
BUILD_EXT=false
CLEAN=false
SERVE=true
YEAR=""
TARGETS=()

while [[ $# -gt 0 ]]; do
    case $1 in
        -c|--channel)        CHANNEL="$2"; shift 2 ;;
        -r|--repo-dir)       REPO_DIR="$2"; shift 2 ;;
        -E|--extensions-dir) EXTENSIONS_DIR="$2"; shift 2 ;;
        -p|--port)           PORT="$2"; shift 2 ;;
        -i|--release-id)     RELEASE_ID="$2"; shift 2 ;;
        --build-ext)         BUILD_EXT=true; shift ;;
        --clean)             CLEAN=true; shift ;;
        --no-serve)          SERVE=false; shift ;;
        -h|--help)           usage; exit 0 ;;
        -*)                  echo "Error: Unknown option $1" >&2; usage >&2; exit 1 ;;
        *)
            if [ -z "$YEAR" ]; then
                YEAR="$1"
            else
                TARGETS+=("$1")
            fi
            shift
            ;;
    esac
done

# --- Validate -----------------------------------------------------------------
if [ -z "$YEAR" ] || [ ${#TARGETS[@]} -eq 0 ]; then
    echo "Error: need a <year> and at least one <target>" >&2
    usage >&2
    exit 1
fi

if ! [[ "$YEAR" =~ ^[0-9]{4}$ ]]; then
    echo "Error: '<year>' should be a 4-digit feed year (e.g. 2026), got '$YEAR'." >&2
    echo "       Did you swap the argument order? Usage: $0 <year> <target> ..." >&2
    exit 1
fi

if [ -z "$EXTENSIONS_DIR" ]; then
    echo "Error: no extensions dir found. Pass -E <dir>, set AVOCADO_EXTENSIONS_DIR," >&2
    echo "       or check out the extensions repos at $REPO_ROOT/../extensions." >&2
    exit 1
fi
if [ ! -d "$EXTENSIONS_DIR" ]; then
    echo "Error: extensions dir '$EXTENSIONS_DIR' not found" >&2
    exit 1
fi

CODENAME="$YEAR/$CHANNEL"
mkdir -p "$REPO_DIR"
REPO_DIR="$(cd "$REPO_DIR" && pwd)"
EXTENSIONS_DIR="$(cd "$EXTENSIONS_DIR" && pwd)"

log "=== Avocado dev feed ==="
log "Feed codename:   $CODENAME"
log "Targets:         ${TARGETS[*]}"
log "Repo dir:        $REPO_DIR"
log "Release id:      $RELEASE_ID"
log "Extensions dir:  $EXTENSIONS_DIR"
log "Mode:            $([ "$CLEAN" = true ] && echo 'clean (per-target reset)' || echo 'incremental')"
log ""

# --- Clean (per-target) -------------------------------------------------------
if [ "$CLEAN" = true ]; then
    log "Resetting target-scoped artifacts..."
    for target in "${TARGETS[@]}"; do
        clean_target "$target"
    done
    log ""
fi

# --- Sync / build -------------------------------------------------------------
build_args=(
    -r "$REPO_DIR"
    -d "$CODENAME"
    -i "$RELEASE_ID"
    -E "$EXTENSIONS_DIR"
)
[ "$BUILD_EXT" = true ] && build_args+=(--build-ext)
build_args+=("${TARGETS[@]}")

log "Populating feed (dev-build.sh)..."
"$SCRIPT_DIR/dev-build.sh" "${build_args[@]}"
log ""

# --- Serve --------------------------------------------------------------------
if [ "$SERVE" = true ]; then
    log "(Re)starting repo server on port $PORT..."
    "$SCRIPT_DIR/dev-start-repo.sh" --restart -r "$REPO_DIR" -p "$PORT" \
        -d "$CODENAME" -i "$RELEASE_ID"
else
    log "Skipping repo server (--no-serve)."
fi

log "✓ Done. Feed: $REPO_DIR/releases/$CODENAME/$RELEASE_ID"
