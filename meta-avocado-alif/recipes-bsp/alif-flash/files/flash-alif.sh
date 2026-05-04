#!/usr/bin/env bash
#
# Wrapper that drives Alif SETOOLS to flash an Alif Ensemble OSPI with the
# stone manifest's TF-A bl32 + DTB + xipImage artifacts.
#
# SETOOLS is closed-source and not redistributable; the user installs it
# themselves into the SDK container (see README.md in the same directory).
# This wrapper expects the SETOOLS entry point to be on $PATH and named
# `app-write-mram` by default; override via AVOCADO_ALIF_FLASH_TOOL.
#
# Inputs (env vars, set by the calling stone-provision-serial.sh):
#   TFA_BIN        - path to bl32.bin
#   KERNEL_DTB     - path to the board DTB
#   KERNEL_BIN     - path to xipImage (post AES + MX rev16 if those are on)
#   ATOC_TEMPLATE  - path to the per-machine ATOC JSON template

set -e
set -u
set -o pipefail

ALIF_FLASH_TOOL="${AVOCADO_ALIF_FLASH_TOOL:-app-write-mram}"

if ! command -v "$ALIF_FLASH_TOOL" >/dev/null 2>&1; then
    cat >&2 <<EOF
ERROR: Alif flash tool '${ALIF_FLASH_TOOL}' not found on PATH.

The Alif Ensemble OSPI is programmed via Alif SETOOLS, which is proprietary
and must be installed into the SDK container manually. See:

  ${BASH_SOURCE[0]%/*}/README.md

To override the tool name, set AVOCADO_ALIF_FLASH_TOOL=<name>.
EOF
    exit 1
fi

: "${TFA_BIN:?TFA_BIN must point to bl32.bin}"
: "${KERNEL_DTB:?KERNEL_DTB must point to the board DTB}"
: "${KERNEL_BIN:?KERNEL_BIN must point to xipImage}"
: "${ATOC_TEMPLATE:?ATOC_TEMPLATE must point to the ATOC JSON template}"

for f in "$TFA_BIN" "$KERNEL_DTB" "$KERNEL_BIN" "$ATOC_TEMPLATE"; do
    if [ ! -f "$f" ]; then
        echo "ERROR: artifact not found: $f" >&2
        exit 1
    fi
done

WORK_DIR=$(mktemp -d)
trap 'rm -rf "$WORK_DIR"' EXIT

ATOC_RESOLVED="${WORK_DIR}/atoc.json"
sed \
    -e "s|\${TFA_BIN}|${TFA_BIN}|g" \
    -e "s|\${KERNEL_DTB}|${KERNEL_DTB}|g" \
    -e "s|\${KERNEL_BIN}|${KERNEL_BIN}|g" \
    "$ATOC_TEMPLATE" > "$ATOC_RESOLVED"

echo "=== Flashing Alif Ensemble OSPI via ${ALIF_FLASH_TOOL} ==="
echo "  TF-A:   ${TFA_BIN}"
echo "  DTB:    ${KERNEL_DTB}"
echo "  Kernel: ${KERNEL_BIN}"
echo "  ATOC:   ${ATOC_RESOLVED}"

"$ALIF_FLASH_TOOL" --config "$ATOC_RESOLVED"

echo "=== OSPI flash complete ==="
