#!/usr/bin/env bash

# Exit immediately if any command fails
set -e
# Exit on undefined variables
set -u
# Propagate errors in pipelines
set -o pipefail

# Environment variables provided by avocado:
# AVOCADO_STONE_MANIFEST  - path to manifest JSON file
# AVOCADO_STONE_BUILD_DIR - build output directory
# AVOCADO_STONE_DATA_DIR  - directory containing manifest-staged input images

# Read component image filenames from the manifest. The bootfiles tarball is
# yocto-static (bootloader, firmware, GPT, programmers, partition XMLs, dtb/efi
# partition vfats, initramfs). The rootfs/var images are built by avocado-cli
# at runtime — extensions applied, users configured — and injected here so the
# device flashes the runtime-correct images, not the yocto-pristine ones.
bootfiles_name=$(jq -r .storage_devices.rootdisk.images.bootfiles "$AVOCADO_STONE_MANIFEST")
rootfs_name=$(jq    -r .storage_devices.rootdisk.images.rootfs    "$AVOCADO_STONE_MANIFEST")
var_name=$(jq       -r .storage_devices.rootdisk.images.var       "$AVOCADO_STONE_MANIFEST")
initramfs_name=$(jq -r .storage_devices.rootdisk.images.initramfs "$AVOCADO_STONE_MANIFEST")
# Declared in object form ({out,size,...}) so `stone validate` does not demand
# a file the build hook has not written yet, so the name is under .out.
efi_name=$(jq -r '(.storage_devices.rootdisk.images.efi // empty) | if type == "object" then (.out // empty) else . end' "$AVOCADO_STONE_MANIFEST")

bootfiles_file="${AVOCADO_STONE_DATA_DIR}/${bootfiles_name}"
rootfs_file="${AVOCADO_STONE_DATA_DIR}/${rootfs_name}"
var_file="${AVOCADO_STONE_DATA_DIR}/${var_name}"

# Stage build dir
build_dir="${AVOCADO_STONE_BUILD_DIR}/ufs"
mkdir -p "$build_dir"

# 1. Extract the static bootfiles bundle
echo "Unpacking bootfiles: $bootfiles_file"
echo "Target directory: $build_dir"
tar -xzf "$bootfiles_file" -C "$build_dir"

# 2. Inject the runtime-built rootfs as system.img (per partition_ufs.xml).
cd "$build_dir/avocado-image-rootfs"
echo "Injecting runtime rootfs as system.img"
cp "$rootfs_file" system.img

# 3. Inject the runtime-built /var. partition_ufs.xml hardcodes the avocado
#    btrfs filename, so we drop it in under that exact name.
echo "Injecting runtime /var as $var_name"
cp "$var_file" "$var_name"

# 4. Inject the ESP that avocado-build-rubikpi3 rebuilt around the pinned
#    kernel. The UKI is not rebuilt here any more -- it has to happen at build
#    time, because an artifact only becomes OTA-updatable and uploadable if it
#    exists before `stone bundle` and is named in the manifest. Rebuilding at
#    provision time meant the boot path was the one part of the OS that could
#    only change by physically reflashing the board.
#
#    But the bootfiles tarball unpacked in step 1 carries its OWN efi.bin --
#    the one linux-avocado-qcom-uki built from the DEFAULT multiconfig's
#    kernel -- and partition_ufs.xml flashes whatever sits at that path. So
#    "the build already did it" is not enough: without this copy the board
#    silently boots the stock kernel while the rootfs carries the pinned
#    kernel's modules, /lib/modules matches nothing, and every modular driver
#    dies (on this board: the USB NIC behind the Renesas bridge, wifi,
#    thermal). Verified the hard way -- twice.
#
#    Fail closed. Flashing the tarball's ESP instead is not a degraded mode,
#    it is a board that boots a kernel nobody asked for.
if [ -n "$efi_name" ]; then
    # Three places, in order of how directly they belong to this provision.
    #
    # The third is the runtime input directory, which is where the build hook
    # writes it. That used to be unnecessary: with no `update` block in the
    # manifest, `stone bundle` staged every declared image into the data dir.
    # Once os_artifacts exists, the data dir's images/ holds the UPDATE
    # artifacts only -- the boot entry -- and the ESP image, which no update
    # ships, stops being copied there at all. Deriving the input dir keeps the
    # provisioned ESP the one the build produced rather than silently falling
    # back to the pristine one in the bootfiles tarball, which carries the
    # default multiconfig's kernel.
    input_dir_guess=$(printf '%s' "$AVOCADO_STONE_DATA_DIR" \
        | sed -e 's#/output/runtimes/#/runtimes/#' -e 's#/stone$##')
    efi_file=""
    for candidate in \
        "${AVOCADO_STONE_DATA_DIR}/${efi_name}" \
        "${AVOCADO_STONE_DATA_DIR}/images/${efi_name}" \
        "${input_dir_guess}/${efi_name}"
    do
        [ -f "$candidate" ] && { efi_file="$candidate"; break; }
    done
    if [ -z "$efi_file" ]; then
        echo "ERROR: manifest declares images.efi as '$efi_name' but no such file" >&2
        echo "       under ${AVOCADO_STONE_DATA_DIR}[/images] or ${input_dir_guess}." >&2
        echo "       Did the avocado-build hook run?" >&2
        exit 1
    fi
    echo "Injecting build-time ESP as efi.bin ($(stat -c%s "$efi_file") bytes)"
    cp "$efi_file" efi.bin
fi

# 5. Wait for QDL device on USB
echo "Waiting for QDL device..."
for i in {1..30}; do
    if lsusb | grep -q "05c6:9008"; then
        echo "QDL device found"
        sleep 1  # let it settle
        break
    fi
    if [ $i -eq 30 ]; then
        echo "ERROR: no QDL device (05c6:9008) after 30 seconds, aborting" >&2
        # 05c6:900e is the SoC's dload/ramdump mode, which is where the board
        # lands after a failed boot and where `reboot edl` from Linux puts it.
        # It looks like EDL and is not: qdl always starts with a Sahara
        # handshake and has no flag to skip it (see `qdl` usage), so a 900e
        # board cannot be flashed. Only a physical power cycle into EDL gets
        # back to 9008. Worth saying out loud -- otherwise this reads as a
        # missing cable or a udev problem.
        if lsusb | grep -q "05c6:900e"; then
            echo "       Board is in dload/ramdump mode (05c6:900e), not EDL." >&2
            echo "       qdl cannot flash that -- power cycle the board into EDL." >&2
        fi
        exit 1
    fi
    sleep 1
done

# 6. Flash via firehose programmer + rawprogram XMLs
qdl --storage ufs prog_firehose_ddr.elf rawprogram*.xml patch*.xml
