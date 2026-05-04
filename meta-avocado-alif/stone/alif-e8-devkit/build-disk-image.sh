#!/usr/bin/env bash
#
# Shared helper for the alif-e8-devkit sd / img provisioning profiles.
# Builds a GPT-formatted SD card image from the rootdisk storage_device in
# the stone manifest. Mirrors the stm32mp25-dk pattern: read partition
# table from JSON, allocate slots, write each partition's image at the
# right offset.
#
# The board's TF-A + xipImage + DTB live in OSPI flash (handled by the
# `serial` profile); this helper only assembles the SD card half.
#
# Inputs (env vars set by caller):
#   AVOCADO_STONE_MANIFEST  - manifest JSON path
#   AVOCADO_STONE_DATA_DIR  - directory containing pre-built images
#   AVOCADO_STONE_BUILD_DIR - directory to write the assembled disk image into
#
# Output: prints the absolute path of the assembled disk image on stdout.

set -e
set -u
set -o pipefail

MANIFEST="$AVOCADO_STONE_MANIFEST"
DATA_DIR="$AVOCADO_STONE_DATA_DIR"
BUILD_DIR="$AVOCADO_STONE_BUILD_DIR"

PLATFORM=$(jq -r '.runtime.platform' "$MANIFEST")
BLOCK_SIZE=$(jq -r '.storage_devices.rootdisk.block_size // 512' "$MANIFEST")

NUM_PARTITIONS=$(jq '.storage_devices.rootdisk.partitions | length' "$MANIFEST")
if [ "$NUM_PARTITIONS" -eq 0 ]; then
    echo "ERROR: no partitions defined in storage_devices.rootdisk" >&2
    exit 1
fi

size_to_kib() {
    local size="$1" unit="$2"
    case "$unit" in
        kibibytes|KiB) echo "$size" ;;
        mebibytes|MiB) echo $(( size * 1024 )) ;;
        gibibytes|GiB) echo $(( size * 1024 * 1024 )) ;;
        *) echo "ERROR: unknown size unit: $unit" >&2; exit 1 ;;
    esac
}

declare -a PART_NAMES PART_SIZES_KIB PART_TYPES PART_UUIDS PART_IMAGES PART_OFFSETS_KIB
CURSOR_KIB=1024  # 1 MiB default offset before the first partition
for i in $(seq 0 $(( NUM_PARTITIONS - 1 ))); do
    name=$(jq -r ".storage_devices.rootdisk.partitions[$i].name // \"\"" "$MANIFEST")
    size=$(jq -r ".storage_devices.rootdisk.partitions[$i].size" "$MANIFEST")
    size_unit=$(jq -r ".storage_devices.rootdisk.partitions[$i].size_unit" "$MANIFEST")
    ptype=$(jq -r ".storage_devices.rootdisk.partitions[$i].partition_type // \"8300\"" "$MANIFEST")
    puuid=$(jq -r ".storage_devices.rootdisk.partitions[$i].partition_uuid // \"\"" "$MANIFEST")
    image=$(jq -r ".storage_devices.rootdisk.partitions[$i].image // \"\"" "$MANIFEST")
    offset=$(jq -r ".storage_devices.rootdisk.partitions[$i].offset // \"\"" "$MANIFEST")
    offset_unit=$(jq -r ".storage_devices.rootdisk.partitions[$i].offset_unit // \"kibibytes\"" "$MANIFEST")

    size_kib=$(size_to_kib "$size" "$size_unit")
    if [ -n "$offset" ]; then
        CURSOR_KIB=$(size_to_kib "$offset" "$offset_unit")
    fi

    PART_NAMES+=("$name")
    PART_SIZES_KIB+=("$size_kib")
    PART_TYPES+=("$ptype")
    PART_UUIDS+=("$puuid")
    PART_IMAGES+=("$image")
    PART_OFFSETS_KIB+=("$CURSOR_KIB")

    CURSOR_KIB=$(( CURSOR_KIB + size_kib ))
done

# Round up to nearest MiB and tack on 1 MiB for the GPT backup header.
TOTAL_KIB=$(( CURSOR_KIB + 1024 ))
TOTAL_MIB=$(( (TOTAL_KIB + 1023) / 1024 ))
IMAGE_FILE="${BUILD_DIR}/avocado-os-${PLATFORM}.img"

echo "=== Building ${IMAGE_FILE} (${TOTAL_MIB} MiB, ${NUM_PARTITIONS} partitions) ===" >&2
truncate -s "${TOTAL_MIB}M" "$IMAGE_FILE"

sgdisk --zap-all "$IMAGE_FILE" >&2

SGDISK_ARGS=()
for i in $(seq 0 $(( NUM_PARTITIONS - 1 ))); do
    pnum=$(( i + 1 ))
    start_sector=$(( PART_OFFSETS_KIB[i] * 2 ))
    size_sectors=$(( PART_SIZES_KIB[i] * 2 ))
    SGDISK_ARGS+=("-n" "${pnum}:${start_sector}:+$(( size_sectors - 1 ))")
    SGDISK_ARGS+=("-t" "${pnum}:${PART_TYPES[i]}")
    if [ -n "${PART_NAMES[i]}" ]; then
        SGDISK_ARGS+=("-c" "${pnum}:${PART_NAMES[i]}")
    fi
    if [ -n "${PART_UUIDS[i]}" ]; then
        SGDISK_ARGS+=("-u" "${pnum}:${PART_UUIDS[i]}")
    fi
done
sgdisk "${SGDISK_ARGS[@]}" "$IMAGE_FILE" >&2

resolve_image_filename() {
    local key="$1" img_type
    img_type=$(jq -r ".storage_devices.rootdisk.images.\"${key}\" | type" "$MANIFEST")
    if [ "$img_type" = "string" ]; then
        jq -r ".storage_devices.rootdisk.images.\"${key}\"" "$MANIFEST"
    else
        jq -r ".storage_devices.rootdisk.images.\"${key}\".out" "$MANIFEST"
    fi
}

# Write each partition's image into the disk at its offset.
for i in $(seq 0 $(( NUM_PARTITIONS - 1 ))); do
    img_key="${PART_IMAGES[i]}"
    [ -z "$img_key" ] && continue

    src="${DATA_DIR}/$(resolve_image_filename "$img_key")"

    if [ ! -f "$src" ]; then
        echo "ERROR: source image not found: $src" >&2
        exit 1
    fi

    echo "  writing ${PART_NAMES[i]} from ${src} at ${PART_OFFSETS_KIB[i]} KiB" >&2
    dd if="$src" of="$IMAGE_FILE" bs=1024 seek="${PART_OFFSETS_KIB[i]}" conv=notrunc status=none
done

echo "$IMAGE_FILE"
