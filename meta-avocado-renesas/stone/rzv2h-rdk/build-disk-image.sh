#!/usr/bin/env bash
#
# Shared helper for the Renesas provisioning profiles; board-agnostic, it reads
# everything it needs from the manifest. This copy serves avocado-rzv2h-rdk,
# whose only image-writing profile is sd.
# Builds a GPT-formatted disk image from the rootdisk storage_device in the
# stone manifest. Mirrors the x86-64 pattern: read partition table from JSON,
# build any FAT images via mtools, then write each partition's image into the
# right offset of a single disk file.
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

size_to_mib() {
    local size="$1" unit="$2"
    case "$unit" in
        mebibytes|MiB) echo "$size" ;;
        kibibytes|KiB) echo $(( size / 1024 )) ;;
        gibibytes|GiB) echo $(( size * 1024 )) ;;
        *) echo "ERROR: unknown size unit: $unit" >&2; exit 1 ;;
    esac
}

declare -a PART_NAMES PART_SIZES_MIB PART_TYPES PART_UUIDS PART_IMAGES PART_OFFSETS_MIB
CURSOR_MIB=1
for i in $(seq 0 $(( NUM_PARTITIONS - 1 ))); do
    name=$(jq -r ".storage_devices.rootdisk.partitions[$i].name // \"\"" "$MANIFEST")
    size=$(jq -r ".storage_devices.rootdisk.partitions[$i].size" "$MANIFEST")
    size_unit=$(jq -r ".storage_devices.rootdisk.partitions[$i].size_unit" "$MANIFEST")
    ptype=$(jq -r ".storage_devices.rootdisk.partitions[$i].partition_type // \"8300\"" "$MANIFEST")
    puuid=$(jq -r ".storage_devices.rootdisk.partitions[$i].partition_uuid // \"\"" "$MANIFEST")
    image=$(jq -r ".storage_devices.rootdisk.partitions[$i].image // \"\"" "$MANIFEST")
    offset=$(jq -r ".storage_devices.rootdisk.partitions[$i].offset // \"\"" "$MANIFEST")
    offset_unit=$(jq -r ".storage_devices.rootdisk.partitions[$i].offset_unit // \"mebibytes\"" "$MANIFEST")

    size_mib=$(size_to_mib "$size" "$size_unit")
    if [ -n "$offset" ]; then
        CURSOR_MIB=$(size_to_mib "$offset" "$offset_unit")
    fi

    PART_NAMES+=("$name")
    PART_SIZES_MIB+=("$size_mib")
    PART_TYPES+=("$ptype")
    PART_UUIDS+=("$puuid")
    PART_IMAGES+=("$image")
    PART_OFFSETS_MIB+=("$CURSOR_MIB")

    CURSOR_MIB=$(( CURSOR_MIB + size_mib ))
done

TOTAL_MIB=$(( CURSOR_MIB + 1 ))
IMAGE_FILE="${BUILD_DIR}/avocado-os-${PLATFORM}.img"

echo "=== Building ${IMAGE_FILE} (${TOTAL_MIB} MiB, ${NUM_PARTITIONS} partitions) ===" >&2
truncate -s "${TOTAL_MIB}M" "$IMAGE_FILE"

sgdisk --zap-all "$IMAGE_FILE" >&2

SGDISK_ARGS=()
for i in $(seq 0 $(( NUM_PARTITIONS - 1 ))); do
    pnum=$(( i + 1 ))
    start_sector=$(( PART_OFFSETS_MIB[i] * 2048 ))
    size_sectors=$(( PART_SIZES_MIB[i] * 2048 ))
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

# Build any FAT-typed images referenced by partitions.
for i in $(seq 0 $(( NUM_PARTITIONS - 1 ))); do
    img_key="${PART_IMAGES[i]}"
    [ -z "$img_key" ] && continue
    build_type=$(jq -r ".storage_devices.rootdisk.images.\"${img_key}\" | if type == \"object\" then .build_args.type // \"\" else \"\" end" "$MANIFEST")
    [ "$build_type" != "fat" ] && continue

    img_out=$(jq -r ".storage_devices.rootdisk.images.\"${img_key}\".out" "$MANIFEST")
    img_size=$(jq -r ".storage_devices.rootdisk.images.\"${img_key}\".size" "$MANIFEST")
    fat_label=$(jq -r ".storage_devices.rootdisk.images.\"${img_key}\".build_args.label // \"BOOT\"" "$MANIFEST")
    fat_img="${BUILD_DIR}/${img_out}"

    echo "=== Building FAT image ${fat_img} (${img_size} MiB) ===" >&2
    truncate -s "${img_size}M" "$fat_img"
    mkfs.fat -F 32 -n "$fat_label" "$fat_img" >&2

    NUM_FILES=$(jq ".storage_devices.rootdisk.images.\"${img_key}\".build_args.files | length" "$MANIFEST")
    for j in $(seq 0 $(( NUM_FILES - 1 ))); do
        f_in=$(jq -r ".storage_devices.rootdisk.images.\"${img_key}\".build_args.files[$j].\"in\"" "$MANIFEST")
        f_out=$(jq -r ".storage_devices.rootdisk.images.\"${img_key}\".build_args.files[$j].out" "$MANIFEST")

        dir_path=$(dirname "$f_out")
        if [ "$dir_path" != "." ]; then
            IFS='/' read -ra DIR_PARTS <<< "$dir_path"
            current=""
            for part in "${DIR_PARTS[@]}"; do
                current="${current}/${part}"
                mmd -i "$fat_img" "::${current}" 2>/dev/null || true
            done
        fi

        echo "  ${f_in} -> ${f_out}" >&2
        mcopy -i "$fat_img" "${DATA_DIR}/${f_in}" "::${f_out}"
    done
done

# Write each partition's image into the disk at its offset.
for i in $(seq 0 $(( NUM_PARTITIONS - 1 ))); do
    img_key="${PART_IMAGES[i]}"
    [ -z "$img_key" ] && continue

    build_type=$(jq -r ".storage_devices.rootdisk.images.\"${img_key}\" | if type == \"object\" then .build_args.type // \"\" else \"\" end" "$MANIFEST")
    if [ "$build_type" = "fat" ]; then
        img_out=$(jq -r ".storage_devices.rootdisk.images.\"${img_key}\".out" "$MANIFEST")
        src="${BUILD_DIR}/${img_out}"
    else
        src="${DATA_DIR}/$(resolve_image_filename "$img_key")"
    fi

    if [ ! -f "$src" ]; then
        echo "ERROR: source image not found: $src" >&2
        exit 1
    fi

    # Guard: refuse to write a source image larger than the partition slot.
    # Without this, dd silently truncates the image and produces a corrupt
    # filesystem — for btrfs this surfaces at first mount as
    #   BTRFS error: device total_bytes should be at most X but found Y
    # which is unhelpful for diagnosing the build-time sizing mismatch.
    src_bytes=$(stat -c '%s' "$src")
    slot_bytes=$(( PART_SIZES_MIB[i] * 1024 * 1024 ))
    if [ "$src_bytes" -gt "$slot_bytes" ]; then
        src_mib=$(( src_bytes / 1024 / 1024 ))
        echo "ERROR: image '${img_key}' (${src_mib} MiB / ${src_bytes} bytes) exceeds partition '${PART_NAMES[i]}' slot (${PART_SIZES_MIB[i]} MiB / ${slot_bytes} bytes)" >&2
        echo "       bump partitions[].size for '${PART_NAMES[i]}' in the stone manifest, or shrink the image." >&2
        exit 1
    fi

    echo "  writing ${PART_NAMES[i]} from ${src} at ${PART_OFFSETS_MIB[i]} MiB" >&2
    dd if="$src" of="$IMAGE_FILE" bs=1M seek="${PART_OFFSETS_MIB[i]}" conv=notrunc status=none
done

echo "$IMAGE_FILE"
