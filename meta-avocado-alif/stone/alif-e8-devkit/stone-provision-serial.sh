#!/usr/bin/env bash
#
# Provisioning for alif-e8-devkit: program OSPI flash with TF-A bl32 +
# xipImage + DTB via the user-supplied Alif SETOOLS / app-write-mram,
# wrapped by the nativesdk-alif-flash recipe's flash-alif.sh helper.
#
# This is a one-time bring-up step: once OSPI has TF-A + kernel + DTB, the
# DevKit boots from OSPI on every reset. The rootfs lives on the SD card,
# provisioned separately via stone-provision-sd.sh.
#
# SETOOLS is closed-source; the user installs it into the SDK container
# manually. See:
#   ${avocado_sdk_datadir}/avocado-alif-flash/README.md

set -e
set -u
set -o pipefail

if [ "${AVOCADO_USB_PASSTHROUGH:-1}" != "1" ]; then
    cat >&2 <<EOF
ERROR: serial provisioning requires USB device passthrough into the SDK so
SETOOLS can talk to the DevKit over its USB CDC interface.
AVOCADO_USB_PASSTHROUGH=${AVOCADO_USB_PASSTHROUGH:-} indicates the SDK was
launched without USB access (likely Docker Desktop). Run on a Linux host or
expose the USB device to the container explicitly.
EOF
    exit 1
fi

MANIFEST="$AVOCADO_STONE_MANIFEST"
DATA_DIR="$AVOCADO_STONE_DATA_DIR"

resolve_image() {
    local key="$1" img_type
    img_type=$(jq -r ".storage_devices.ospi.images.\"${key}\" | type" "$MANIFEST")
    if [ "$img_type" = "string" ]; then
        jq -r ".storage_devices.ospi.images.\"${key}\"" "$MANIFEST"
    else
        jq -r ".storage_devices.ospi.images.\"${key}\".out" "$MANIFEST"
    fi
}

TFA_REL=$(resolve_image tfa)
KERNEL_REL=$(resolve_image kernel)
DTB_REL=$(resolve_image dtb)

TFA_BIN="${DATA_DIR}/${TFA_REL}"
KERNEL_BIN="${DATA_DIR}/${KERNEL_REL}"
KERNEL_DTB="${DATA_DIR}/${DTB_REL}"

for f in "$TFA_BIN" "$KERNEL_BIN" "$KERNEL_DTB"; do
    if [ ! -f "$f" ]; then
        echo "ERROR: missing artifact: $f" >&2
        exit 1
    fi
done

# nativesdk-alif-flash deploys flash-alif.sh as bindir/avocado-alif-flash
# and the per-machine ATOC template alongside it under datadir.
WRAPPER="${AVOCADO_ALIF_FLASH_WRAPPER:-avocado-alif-flash}"
ATOC_TEMPLATE="${AVOCADO_ALIF_ATOC_TEMPLATE:-/usr/share/avocado-alif-flash/atoc-alif-e8-devkit.json}"

if ! command -v "$WRAPPER" >/dev/null 2>&1; then
    echo "ERROR: $WRAPPER not on PATH; nativesdk-alif-flash may not be installed in the SDK container." >&2
    exit 1
fi
if [ ! -f "$ATOC_TEMPLATE" ]; then
    echo "ERROR: ATOC template not found at $ATOC_TEMPLATE; override with AVOCADO_ALIF_ATOC_TEMPLATE=." >&2
    exit 1
fi

cat <<EOF

================================================================
Alif Ensemble E8 DevKit OSPI provisioning (Alif SETOOLS)

Before continuing, confirm:
  1. SETOOLS / app-write-mram is installed and on PATH inside the SDK
     container (see /usr/share/avocado-alif-flash/README.md for the
     install steps).
  2. The DevKit's USB CDC port is connected to this host and the board
     is powered on in service / programming mode.

Press Enter to start flashing, or Ctrl-C to abort.
================================================================
EOF
read -r _

TFA_BIN="$TFA_BIN" \
KERNEL_BIN="$KERNEL_BIN" \
KERNEL_DTB="$KERNEL_DTB" \
ATOC_TEMPLATE="$ATOC_TEMPLATE" \
    "$WRAPPER"

cat <<EOF

================================================================
OSPI provisioning complete.

Next steps:
  1. Run 'avocado provision alif-e8-devkit --profile sd' to write the SD
     card with the avocado rootfs.
  2. Insert the SD card and power-cycle: TF-A + xipImage boot from OSPI,
     mount /dev/mmcblk1p2 as rootfs.
================================================================
EOF
