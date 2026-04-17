#!/usr/bin/env bash

# Common functions for RPi tryboot provisioning scripts.
#
# These replace fwup-based provisioning with native tools (sfdisk, dd, mcopy)
# for targets using the tryboot A/B boot mechanism.
#
# Uses GPT partition table with partition labels (PARTLABELs) for
# storage-agnostic device identification.

# --- Disk image creation ---

# create_tryboot_disk_image <manifest> <build_dir> <image_path>
#
# Creates a raw disk image with a GPT partition table and writes each
# partition image at its correct offset. Reads partition layout from
# the stone manifest JSON.
create_tryboot_disk_image() {
    local manifest="$1"
    local build_dir="$2"
    local image_path="$3"

    local block_size
    block_size=$(jq -r '.storage_devices.rootdisk.block_size // 512' "$manifest")

    # Read partitions into arrays
    local -a part_names part_offsets part_sizes part_images part_offset_units part_size_units part_expands part_uuids
    local idx=0

    while IFS= read -r line; do
        part_names[$idx]=$(echo "$line" | jq -r '.name // empty')
        part_offsets[$idx]=$(echo "$line" | jq -r '.offset // 0')
        part_offset_units[$idx]=$(echo "$line" | jq -r '.offset_unit // "mebibytes"')
        part_sizes[$idx]=$(echo "$line" | jq -r '.size')
        part_size_units[$idx]=$(echo "$line" | jq -r '.size_unit')
        part_images[$idx]=$(echo "$line" | jq -r '.image // empty')
        part_expands[$idx]=$(echo "$line" | jq -r '.expand // empty')
        part_uuids[$idx]=$(echo "$line" | jq -r '.partition_uuid // empty')
        idx=$((idx + 1))
    done < <(jq -c '.storage_devices.rootdisk.partitions[]' "$manifest")

    local num_parts=$idx

    # Convert offsets and sizes to bytes, compute sequential offsets
    local -a offset_bytes size_bytes
    local cursor=1048576  # Start at 1 MiB (leave space for GPT header + alignment)

    for ((i = 0; i < num_parts; i++)); do
        size_bytes[$i]=$(to_bytes "${part_sizes[$i]}" "${part_size_units[$i]}")

        if [[ "${part_offsets[$i]}" != "0" && -n "${part_offsets[$i]}" ]]; then
            offset_bytes[$i]=$(to_bytes "${part_offsets[$i]}" "${part_offset_units[$i]}")
            cursor=$(( ${offset_bytes[$i]} + ${size_bytes[$i]} ))
        else
            # Align to 1 MiB boundary
            cursor=$(( (cursor + 1048575) / 1048576 * 1048576 ))
            offset_bytes[$i]=$cursor
            cursor=$(( cursor + ${size_bytes[$i]} ))
        fi
    done

    # Total image size: partitions + 1 MiB for backup GPT at end of disk
    local total_bytes=$(( cursor + 1048576 ))
    echo "Creating disk image: $image_path ($(( total_bytes / 1048576 )) MiB)"
    truncate -s "$total_bytes" "$image_path"

    # Build sfdisk script with GPT partition labels
    local sfdisk_script="label: gpt\n"

    for ((i = 0; i < num_parts; i++)); do
        local start=$(( ${offset_bytes[$i]} / $block_size ))
        local count=$(( ${size_bytes[$i]} / $block_size ))

        # GPT partition type GUIDs
        local ptype_guid=""
        case "${part_names[$i]}" in
            boot-*|uboot-env)
                # Microsoft basic data (FAT partitions)
                ptype_guid="EBD0A0A2-B9E5-4433-87C0-68B6B72699C7"
                ;;
            *)
                # Linux filesystem
                ptype_guid="0FC63DAF-8483-4772-8E79-3D69D8477DE4"
                ;;
        esac

        local uuid_attr=""
        if [[ -n "${part_uuids[$i]}" ]]; then
            uuid_attr=", uuid=${part_uuids[$i]}"
        fi

        sfdisk_script+="start=${start}, size=${count}, type=${ptype_guid}, name=${part_names[$i]}${uuid_attr}\n"
    done

    echo -e "$sfdisk_script" | sfdisk "$image_path"
    echo "Partition table created."

    # Write each image at its offset
    for ((i = 0; i < num_parts; i++)); do
        local img_key="${part_images[$i]}"
        if [[ -z "$img_key" ]]; then continue; fi

        # Resolve image filename from manifest.
        # Images can be objects ({"out": "file.img", ...}) or plain strings ("file.img").
        local img_out
        img_out=$(jq -r ".storage_devices.rootdisk.images[\"${img_key}\"] | if type == \"object\" then .out else . end // empty" "$manifest")
        if [[ -z "$img_out" || "$img_out" == "null" ]]; then continue; fi

        local img_path="${build_dir}/${img_out}"
        if [[ ! -f "$img_path" ]]; then
            echo "Warning: Image '$img_out' not found at '$img_path', skipping"
            continue
        fi

        echo "  Writing ${part_names[$i]} (${img_out}) at offset ${offset_bytes[$i]}"
        dd if="$img_path" of="$image_path" bs=1M seek=$(( ${offset_bytes[$i]} / 1048576 )) conv=notrunc status=none
    done

    echo "Disk image created: $image_path"
}

# --- U-Boot environment patching ---

# patch_uboot_env <image_path> <manifest> <key> <value> [<key> <value> ...]
#
# Extracts the U-Boot env from the image, patches it with fw_setenv,
# and writes it back.
patch_uboot_env() {
    local image_path="$1"
    local manifest="$2"
    shift 2

    local env_offset_bytes
    env_offset_bytes=$(get_partition_offset_bytes "$manifest" "uboot-env")

    local env_workdir="${AVOCADO_STONE_BUILD_DIR}/uboot-env-work"
    mkdir -p "$env_workdir"

    echo "Extracting env files from image at offset $env_offset_bytes..."
    mcopy -i "${image_path}@@${env_offset_bytes}" ::/uboot.env "${env_workdir}/uboot.env"
    mcopy -i "${image_path}@@${env_offset_bytes}" ::/uboot.env.redund "${env_workdir}/uboot.env.redund"

    local fw_env_config="${AVOCADO_STONE_BUILD_DIR}/fw_env_img.config"
    cat > "$fw_env_config" << EOF
${env_workdir}/uboot.env	0x0	0x20000
${env_workdir}/uboot.env.redund	0x0	0x20000
EOF

    # Set env vars from arguments (key value pairs)
    while [[ $# -ge 2 ]]; do
        local key="$1" value="$2"
        shift 2
        fw_setenv -c "$fw_env_config" "$key" "$value"
    done

    echo "Writing patched env back to image..."
    mcopy -o -i "${image_path}@@${env_offset_bytes}" "${env_workdir}/uboot.env" ::/uboot.env
    mcopy -o -i "${image_path}@@${env_offset_bytes}" "${env_workdir}/uboot.env.redund" ::/uboot.env.redund

    rm -rf "$env_workdir" "$fw_env_config"
}

# --- cmdline.txt patching ---

# patch_cmdline <image_path> <boot_part_name> <manifest> <sed-expr> [...]
#
# Patches cmdline.txt on a boot partition within the image.
# Each argument after the manifest is a sed expression applied to cmdline.txt.
patch_cmdline() {
    local image_path="$1"
    local boot_part_name="$2"
    local manifest="$3"
    shift 3

    local boot_offset_bytes
    boot_offset_bytes=$(get_partition_offset_bytes "$manifest" "$boot_part_name")

    local tmpdir="${AVOCADO_STONE_BUILD_DIR}/cmdline-patch"
    mkdir -p "$tmpdir"

    mcopy -i "${image_path}@@${boot_offset_bytes}" ::/cmdline.txt "${tmpdir}/cmdline.txt"

    for expr in "$@"; do
        sed -i "$expr" "${tmpdir}/cmdline.txt"
    done

    mcopy -o -i "${image_path}@@${boot_offset_bytes}" "${tmpdir}/cmdline.txt" ::/cmdline.txt
    rm -rf "$tmpdir"
}

# --- Helpers ---

to_bytes() {
    local value="$1"
    local unit="$2"
    case "$unit" in
        mebibytes) echo $(( value * 1048576 )) ;;
        kibibytes) echo $(( value * 1024 )) ;;
        bytes) echo "$value" ;;
        *) echo "Error: Unknown unit: $unit" >&2; exit 1 ;;
    esac
}

# Compute the byte offset of a named partition from the manifest.
# Handles both explicit offsets and sequential (computed) offsets.
get_partition_offset_bytes() {
    local manifest="$1"
    local part_name="$2"

    local cursor=1048576  # Start at 1 MiB
    while IFS= read -r line; do
        local name offset offset_unit size size_unit
        name=$(echo "$line" | jq -r '.name // empty')
        offset=$(echo "$line" | jq -r '.offset // 0')
        offset_unit=$(echo "$line" | jq -r '.offset_unit // "mebibytes"')
        size=$(echo "$line" | jq -r '.size')
        size_unit=$(echo "$line" | jq -r '.size_unit')

        local size_b
        size_b=$(to_bytes "$size" "$size_unit")

        if [[ "$offset" != "0" && -n "$offset" && "$offset" != "null" ]]; then
            cursor=$(to_bytes "$offset" "$offset_unit")
        else
            cursor=$(( (cursor + 1048575) / 1048576 * 1048576 ))
        fi

        if [[ "$name" == "$part_name" ]]; then
            echo "$cursor"
            return 0
        fi

        cursor=$(( cursor + size_b ))
    done < <(jq -c '.storage_devices.rootdisk.partitions[]' "$manifest")

    echo "Error: partition '$part_name' not found in manifest" >&2
    return 1
}

# Extract the archive (tar) produced by stone build for tryboot targets.
# Extracts images into the build directory.
extract_archive() {
    local archive_file="$1"
    local build_dir="$2"

    echo "Extracting archive: $archive_file"
    tar xf "$archive_file" -C "$build_dir"
}
