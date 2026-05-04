#!/usr/bin/env bash
#
# Shared helper for the orangepi-5-plus img/sd/emmc/nvme provisioning
# profiles. Builds a GPT-formatted disk image from the rootdisk
# storage_device in the stone manifest.
#
# Differences from the rzv2n build-disk-image.sh this is forked from:
#   - All sizes/offsets tracked in 512-byte sectors (rockchip's bootloader
#     pieces sit at sub-MiB offsets: idbloader.img at LBA 64, u-boot.itb at
#     LBA 16384). MiB precision is too coarse.
#   - Partition entries with "in-partition-table": "false" are dd'd into
#     the disk at their declared offset but get NO GPT entry. Used for
#     idbloader and u-boot.itb which Rockchip BootROM/SPL find by raw LBA,
#     not by partition table.
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

if [ "$BLOCK_SIZE" != "512" ]; then
    echo "ERROR: only 512-byte blocks supported (manifest declares ${BLOCK_SIZE})" >&2
    exit 1
fi

NUM_PARTITIONS=$(jq '.storage_devices.rootdisk.partitions | length' "$MANIFEST")
if [ "$NUM_PARTITIONS" -eq 0 ]; then
    echo "ERROR: no partitions defined in storage_devices.rootdisk" >&2
    exit 1
fi

# All values normalised to sectors (1 sector = 512 bytes).
size_to_sectors() {
    local size="$1" unit="$2"
    case "$unit" in
        sectors)             echo "$size" ;;
        kibibytes|KiB)       echo $(( size * 2 )) ;;
        mebibytes|MiB)       echo $(( size * 2048 )) ;;
        gibibytes|GiB)       echo $(( size * 2097152 )) ;;
        *) echo "ERROR: unknown size unit: $unit" >&2; exit 1 ;;
    esac
}

declare -a P_NAME P_SIZE_SEC P_TYPE P_UUID P_IMAGE P_OFFSET_SEC P_IN_TABLE

# Default cursor: leave room for protective MBR (sector 0) + GPT primary
# header and partition table (sectors 1-33). First raw write or partition
# starts at or after sector 34. Rockchip's idbloader at sector 64 sits in
# this reserved area which is fine.
CURSOR_SEC=34

for i in $(seq 0 $(( NUM_PARTITIONS - 1 ))); do
    name=$(jq -r ".storage_devices.rootdisk.partitions[$i].name // \"\"" "$MANIFEST")
    size=$(jq -r ".storage_devices.rootdisk.partitions[$i].size" "$MANIFEST")
    size_unit=$(jq -r ".storage_devices.rootdisk.partitions[$i].size_unit" "$MANIFEST")
    ptype=$(jq -r ".storage_devices.rootdisk.partitions[$i].partition_type // \"8300\"" "$MANIFEST")
    puuid=$(jq -r ".storage_devices.rootdisk.partitions[$i].partition_uuid // \"\"" "$MANIFEST")
    image=$(jq -r ".storage_devices.rootdisk.partitions[$i].image // \"\"" "$MANIFEST")
    offset=$(jq -r ".storage_devices.rootdisk.partitions[$i].offset // \"\"" "$MANIFEST")
    offset_unit=$(jq -r ".storage_devices.rootdisk.partitions[$i].offset_unit // \"mebibytes\"" "$MANIFEST")
    in_table=$(jq -r ".storage_devices.rootdisk.partitions[$i].\"in-partition-table\" // \"true\"" "$MANIFEST")

    size_sec=$(size_to_sectors "$size" "$size_unit")
    if [ -n "$offset" ]; then
        CURSOR_SEC=$(size_to_sectors "$offset" "$offset_unit")
    fi

    P_NAME+=("$name")
    P_SIZE_SEC+=("$size_sec")
    P_TYPE+=("$ptype")
    P_UUID+=("$puuid")
    P_IMAGE+=("$image")
    P_OFFSET_SEC+=("$CURSOR_SEC")
    P_IN_TABLE+=("$in_table")

    CURSOR_SEC=$(( CURSOR_SEC + size_sec ))
done

# Round up to a MiB boundary for the secondary GPT footer. truncate -s takes
# bytes; convert from sectors.
TOTAL_SEC=$(( CURSOR_SEC + 2048 ))    # +1 MiB tail for GPT secondary
TOTAL_BYTES=$(( TOTAL_SEC * 512 ))
IMAGE_FILE="${BUILD_DIR}/avocado-os-${PLATFORM}.img"

echo "=== Building ${IMAGE_FILE} ($(( TOTAL_BYTES / 1048576 )) MiB, ${NUM_PARTITIONS} partition entries) ===" >&2
truncate -s "${TOTAL_BYTES}" "$IMAGE_FILE"

sgdisk --zap-all "$IMAGE_FILE" >&2

# sgdisk numbering tracks only entries that go IN the GPT table.
SGDISK_ARGS=()
pnum=0
for i in $(seq 0 $(( NUM_PARTITIONS - 1 ))); do
    [ "${P_IN_TABLE[i]}" = "true" ] || continue
    pnum=$(( pnum + 1 ))
    start=${P_OFFSET_SEC[i]}
    size=${P_SIZE_SEC[i]}
    SGDISK_ARGS+=("-n" "${pnum}:${start}:+$(( size - 1 ))")
    SGDISK_ARGS+=("-t" "${pnum}:${P_TYPE[i]}")
    if [ -n "${P_NAME[i]}" ]; then
        SGDISK_ARGS+=("-c" "${pnum}:${P_NAME[i]}")
    fi
    if [ -n "${P_UUID[i]}" ]; then
        SGDISK_ARGS+=("-u" "${pnum}:${P_UUID[i]}")
    fi
done
if [ ${#SGDISK_ARGS[@]} -gt 0 ]; then
    sgdisk "${SGDISK_ARGS[@]}" "$IMAGE_FILE" >&2
fi

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
    img_key="${P_IMAGE[i]}"
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

# Write each entry's image into the disk at its offset. Both GPT-table
# entries and raw (in-partition-table=false) entries are written the same
# way -- the only difference is whether sgdisk recorded a header for them.
for i in $(seq 0 $(( NUM_PARTITIONS - 1 ))); do
    img_key="${P_IMAGE[i]}"
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

    echo "  writing ${P_NAME[i]} from $(basename "$src") at sector ${P_OFFSET_SEC[i]}" >&2
    dd if="$src" of="$IMAGE_FILE" bs=512 seek="${P_OFFSET_SEC[i]}" conv=notrunc status=none
done

echo "$IMAGE_FILE"
