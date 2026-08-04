#!/usr/bin/env bash

# Disk Image Provisioning Script for Intel x86-64
#
# Creates a complete GPT disk image from the stone manifest partition table.
# Partition layout, sizes, types, and UUIDs are all read from the manifest JSON.
#
# Environment variables provided by avocado/stone:
# AVOCADO_STONE_MANIFEST  - path to manifest JSON file
# AVOCADO_STONE_BUILD_DIR - build output directory
# AVOCADO_STONE_DATA_DIR  - stone data directory
# AVOCADO_PROVISION_OUT   - (optional) output directory for final image

set -e
set -u
set -o pipefail

MANIFEST="$AVOCADO_STONE_MANIFEST"
DATA_DIR="$AVOCADO_STONE_DATA_DIR"
BUILD_DIR="$AVOCADO_STONE_BUILD_DIR"

# Read platform and image references from manifest
PLATFORM=$(jq -r '.runtime.platform' "$MANIFEST")
BLOCK_SIZE=$(jq -r '.storage_devices.rootdisk.block_size // 512' "$MANIFEST")

# Every sector calculation below converts MiB with a hardcoded "* 2048", which
# is only correct for 512-byte sectors. Refuse anything else rather than emit a
# partition table whose offsets are wrong by the block-size ratio.
if [ "$BLOCK_SIZE" != "512" ]; then
    echo "ERROR: only 512-byte blocks supported (manifest declares ${BLOCK_SIZE})" >&2
    exit 1
fi

echo "=== Creating disk image for ${PLATFORM} ==="
echo "  Data directory: ${DATA_DIR}"
echo "  Build directory: ${BUILD_DIR}"

# =============================================================================
# Read partition table from manifest
# =============================================================================
# Each partition has: name, size, size_unit, partition_type, partition_uuid (optional),
# offset/offset_unit (optional), image (optional), expand (optional)

NUM_PARTITIONS=$(jq '.storage_devices.rootdisk.partitions | length' "$MANIFEST")
if [ "$NUM_PARTITIONS" -eq 0 ]; then
    echo "ERROR: No partitions defined in manifest"
    exit 1
fi

echo "  Partitions: ${NUM_PARTITIONS}"

# Convert size_unit to MiB multiplier
size_to_mib() {
    local size="$1"
    local unit="$2"
    case "$unit" in
        mebibytes|MiB) echo "$size" ;;
        kibibytes|KiB) echo $(( size / 1024 )) ;;
        gibibytes|GiB) echo $(( size * 1024 )) ;;
        *) echo "ERROR: Unknown size unit: $unit" >&2; exit 1 ;;
    esac
}

# Resolve an image key to its filename: images.<key> is either a string
# (the filename) or an object with an "out" field.
resolve_image_filename() {
    local image_key="$1"
    local img_type
    img_type=$(jq -r ".storage_devices.rootdisk.images.\"${image_key}\" | type" "$MANIFEST")
    if [ "$img_type" = "string" ]; then
        jq -r ".storage_devices.rootdisk.images.\"${image_key}\"" "$MANIFEST"
    else
        jq -r ".storage_devices.rootdisk.images.\"${image_key}\".out" "$MANIFEST"
    fi
}

# Copy an image into the disk image at a byte offset. conv=sparse skips zero
# blocks (partitions are largely empty), so the write is fast and the .img stays
# sparse. Progress is emitted as periodic newlines so it renders in captured
# (non-TTY) provisioning logs -- dd's \r-based status=progress does not.
write_image() {
    local src="$1" dst="$2" seek_mib="$3" label="$4"
    local total_bytes total_mib dd_pid pos written seek_bytes
    total_bytes=$(stat -c%s "$src")
    total_mib=$(( (total_bytes + 1048575) / 1048576 ))
    seek_bytes=$(( seek_mib * 1048576 ))
    echo "  Writing ${label}: ${total_mib} MiB"

    # bs=1M with a whole-MiB seek avoids the newer oflag=seek_bytes dd operand.
    dd if="$src" of="$dst" bs=1M seek="$seek_mib" \
       conv=notrunc,sparse status=none </dev/null &
    dd_pid=$!
    while kill -0 "$dd_pid" 2>/dev/null; do
        sleep 3
        pos=$(awk '/^pos:/ {print $2}' "/proc/${dd_pid}/fdinfo/1" 2>/dev/null || echo "")
        if [ -n "$pos" ] && [ "$total_bytes" -gt 0 ] 2>/dev/null; then
            written=$(( pos - seek_bytes )); [ "$written" -lt 0 ] && written=0
            printf '    %d / %d MiB (%d%%)\n' \
                "$(( written / 1048576 ))" "$total_mib" "$(( written * 100 / total_bytes ))"
        fi
    done
    wait "$dd_pid"
}

# Return an image's build_args.type, or "" when the image is a plain filename
# string (jq errors if you index a string with .build_args, and `//` does not
# rescue an error -- only null/false).
image_build_type() {
    jq -r --arg k "$1" '.storage_devices.rootdisk.images[$k] | if type == "object" then (.build_args.type // "") else "" end' "$MANIFEST"
}

# Build partition info arrays
declare -a PART_NAMES PART_SIZES_MIB PART_TYPES PART_UUIDS PART_IMAGES PART_OFFSETS_MIB PART_EXPAND
GPT_START_MIB=1
CURSOR_MIB=${GPT_START_MIB}

for i in $(seq 0 $(( NUM_PARTITIONS - 1 ))); do
    name=$(jq -r ".storage_devices.rootdisk.partitions[$i].name // \"\"" "$MANIFEST")
    size=$(jq -r ".storage_devices.rootdisk.partitions[$i].size" "$MANIFEST")
    size_unit=$(jq -r ".storage_devices.rootdisk.partitions[$i].size_unit" "$MANIFEST")
    ptype=$(jq -r ".storage_devices.rootdisk.partitions[$i].partition_type // \"8300\"" "$MANIFEST")
    puuid=$(jq -r ".storage_devices.rootdisk.partitions[$i].partition_uuid // \"\"" "$MANIFEST")
    image=$(jq -r ".storage_devices.rootdisk.partitions[$i].image // \"\"" "$MANIFEST")
    offset=$(jq -r ".storage_devices.rootdisk.partitions[$i].offset // \"\"" "$MANIFEST")
    offset_unit=$(jq -r ".storage_devices.rootdisk.partitions[$i].offset_unit // \"mebibytes\"" "$MANIFEST")
    expand=$(jq -r ".storage_devices.rootdisk.partitions[$i].expand // \"\"" "$MANIFEST")

    # A partition marked "expand" (e.g. var) carries no explicit size in the
    # manifest -- its size is dynamic, driven by whatever the build put into its
    # image. Size it to hold its own image (rounded up to a whole MiB) for the
    # flashed image; stone grows it to fill the disk on the target after flashing.
    if [ "$expand" = "true" ] || [ "$size" = "null" ] || [ -z "$size" ]; then
        if [ -z "$image" ] || [ "$image" = "null" ]; then
            echo "ERROR: partition '${name}' is expand/sizeless but has no image to size from" >&2
            exit 1
        fi
        img_filename=$(resolve_image_filename "$image")
        img_path="${DATA_DIR}/${img_filename}"
        if [ ! -f "$img_path" ]; then
            echo "ERROR: cannot size expand partition '${name}': image not found: ${img_path}" >&2
            exit 1
        fi
        img_bytes=$(stat -c%s "$img_path")
        size_mib=$(( (img_bytes + 1048575) / 1048576 ))
    else
        size_mib=$(size_to_mib "$size" "$size_unit")
    fi

    # Use explicit offset if provided, otherwise use cursor
    if [ -n "$offset" ]; then
        offset_mib=$(size_to_mib "$offset" "$offset_unit")
        CURSOR_MIB=$offset_mib
    fi

    PART_NAMES+=("$name")
    PART_SIZES_MIB+=("$size_mib")
    PART_TYPES+=("$ptype")
    PART_UUIDS+=("$puuid")
    PART_IMAGES+=("$image")
    PART_OFFSETS_MIB+=("$CURSOR_MIB")
    PART_EXPAND+=("$expand")

    echo "  Partition $((i+1)): ${name:-unnamed}  offset=${CURSOR_MIB}MiB  size=${size_mib}MiB  type=${ptype}${puuid:+  uuid=${puuid}}${image:+  image=${image}}"

    CURSOR_MIB=$(( CURSOR_MIB + size_mib ))
done

# Total image size (partitions + 1 MiB GPT tail)
TOTAL_MIB=$(( CURSOR_MIB + 1 ))

IMAGE_NAME="avocado-os-${PLATFORM}.img"
IMAGE_FILE="${BUILD_DIR}/${IMAGE_NAME}"

echo "  Total image: ${TOTAL_MIB} MiB"

# =============================================================================
# Create raw disk image
# =============================================================================
echo ""
echo "=== Creating raw disk image ==="
truncate -s "${TOTAL_MIB}M" "$IMAGE_FILE"

# =============================================================================
# Create GPT partition table from manifest
# =============================================================================
echo "=== Creating GPT partition table ==="

sgdisk --zap-all "$IMAGE_FILE"

SGDISK_ARGS=""
for i in $(seq 0 $(( NUM_PARTITIONS - 1 ))); do
    pnum=$((i + 1))
    start_sector=$(( ${PART_OFFSETS_MIB[$i]} * 2048 ))
    size_sectors=$(( ${PART_SIZES_MIB[$i]} * 2048 ))
    # sgdisk's "+N" end means N sectors (end = start + N - 1). Using size_sectors-1
    # here made every partition one sector short -- harmless for images smaller
    # than their partition, but fatal for var, whose btrfs is sized to the exact
    # partition (btrfs then reports "device total_bytes should be at most ...").
    SGDISK_ARGS="${SGDISK_ARGS} -n ${pnum}:${start_sector}:+${size_sectors}"
    SGDISK_ARGS="${SGDISK_ARGS} -t ${pnum}:${PART_TYPES[$i]}"

    if [ -n "${PART_NAMES[$i]}" ]; then
        SGDISK_ARGS="${SGDISK_ARGS} -c ${pnum}:${PART_NAMES[$i]}"
    fi

    if [ -n "${PART_UUIDS[$i]}" ]; then
        SGDISK_ARGS="${SGDISK_ARGS} -u ${pnum}:${PART_UUIDS[$i]}"
    fi
done

# shellcheck disable=SC2086
sgdisk $SGDISK_ARGS "$IMAGE_FILE"
echo "  Partition table created"

# =============================================================================
# Build boot image (FAT32 ESP) if needed
# =============================================================================
# Check if any partition has an image that is a FAT build object
BOOT_IMAGE_KEY=""
for i in $(seq 0 $(( NUM_PARTITIONS - 1 ))); do
    img_key="${PART_IMAGES[$i]}"
    if [ -z "$img_key" ]; then continue; fi

    build_type=$(image_build_type "$img_key")
    if [ "$build_type" = "fat" ]; then
        BOOT_IMAGE_KEY="$img_key"
        break
    fi
done

if [ -n "$BOOT_IMAGE_KEY" ]; then
    echo "=== Creating FAT boot image (${BOOT_IMAGE_KEY}) ==="

    # mtools prompts on /dev/tty for filesystem "consistency" questions (e.g. the
    # disk-geometry mismatch of a plain image file), which hangs a non-interactive
    # provision. Skip those checks so every mtools call stays non-interactive.
    export MTOOLS_SKIP_CHECK=1

    BOOT_IMG_OUT=$(jq -r ".storage_devices.rootdisk.images.\"${BOOT_IMAGE_KEY}\".out" "$MANIFEST")
    BOOT_IMG_SIZE=$(jq -r ".storage_devices.rootdisk.images.\"${BOOT_IMAGE_KEY}\".size" "$MANIFEST")
    BOOT_IMG="${BUILD_DIR}/${BOOT_IMG_OUT}"

    truncate -s "${BOOT_IMG_SIZE}M" "$BOOT_IMG"
    mkfs.fat -F 32 -n "BOOT" "$BOOT_IMG"

    if ! command -v mcopy >/dev/null 2>&1; then
        echo "ERROR: mtools (mcopy) not found - required for FAT image creation"
        exit 1
    fi

    # Copy each file listed in build_args.files. Track directories we've already
    # created: running `mmd` on an existing directory makes mtools prompt on
    # /dev/tty (hanging a non-interactive provision), so create each unique dir
    # exactly once. stdin is redirected from /dev/null as a backstop.
    declare -A CREATED_DIRS=()
    NUM_FILES=$(jq ".storage_devices.rootdisk.images.\"${BOOT_IMAGE_KEY}\".build_args.files | length" "$MANIFEST")
    for j in $(seq 0 $(( NUM_FILES - 1 ))); do
        file_in=$(jq -r ".storage_devices.rootdisk.images.\"${BOOT_IMAGE_KEY}\".build_args.files[$j].\"in\"" "$MANIFEST")
        file_out=$(jq -r ".storage_devices.rootdisk.images.\"${BOOT_IMAGE_KEY}\".build_args.files[$j].out" "$MANIFEST")

        # Create parent directories (each unique path once, parents first)
        dir_path=$(dirname "$file_out")
        if [ "$dir_path" != "." ]; then
            IFS='/' read -ra DIR_PARTS <<< "$dir_path"
            current=""
            for part in "${DIR_PARTS[@]}"; do
                current="${current}/${part}"
                if [ -z "${CREATED_DIRS[$current]:-}" ]; then
                    mmd -i "$BOOT_IMG" "::${current}" </dev/null >/dev/null 2>&1 || true
                    CREATED_DIRS[$current]=1
                fi
            done
        fi

        echo "  Adding: ${file_in} -> ${file_out}"
        mcopy -i "$BOOT_IMG" "${DATA_DIR}/${file_in}" "::${file_out}" </dev/null
    done

    echo "  FAT boot image created: ${BOOT_IMG}"
fi

# =============================================================================
# Write partition images into disk image
# =============================================================================
echo "=== Writing partition images ==="

for i in $(seq 0 $(( NUM_PARTITIONS - 1 ))); do
    img_key="${PART_IMAGES[$i]}"
    if [ -z "$img_key" ]; then continue; fi

    # Resolve the actual image file path
    build_type=$(image_build_type "$img_key")
    if [ "$build_type" = "fat" ]; then
        # FAT image was built above
        img_out=$(jq -r ".storage_devices.rootdisk.images.\"${img_key}\".out" "$MANIFEST")
        img_file="${BUILD_DIR}/${img_out}"
    else
        img_filename=$(resolve_image_filename "$img_key")
        img_file="${DATA_DIR}/${img_filename}"
    fi

    if [ ! -f "$img_file" ]; then
        echo "ERROR: Image file not found: ${img_file}"
        exit 1
    fi

    write_image "$img_file" "$IMAGE_FILE" "${PART_OFFSETS_MIB[$i]}" "${PART_NAMES[$i]}"
done

# Cleanup built images
if [ -n "$BOOT_IMAGE_KEY" ]; then
    img_out=$(jq -r ".storage_devices.rootdisk.images.\"${BOOT_IMAGE_KEY}\".out" "$MANIFEST")
    rm -f "${BUILD_DIR}/${img_out}"
fi

echo ""
echo "=== Disk image created: ${IMAGE_FILE} ==="
echo "  Size: $(du -h "$IMAGE_FILE" | cut -f1)"

# Copy to output directory if specified
if [ -n "${AVOCADO_PROVISION_OUT:-}" ]; then
    mkdir -p "$AVOCADO_PROVISION_OUT"
    cp -v "$IMAGE_FILE" "$AVOCADO_PROVISION_OUT/"
    echo "  Copied to: ${AVOCADO_PROVISION_OUT}/${IMAGE_NAME}"
fi
