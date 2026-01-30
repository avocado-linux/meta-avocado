#!/usr/bin/env bash

# Exit immediately if any command fails
set -e
# Exit on undefined variables
set -u
# Propagate errors in pipelines
set -o pipefail

# Environment variables provided by avocado:
# AVOCADO_STONE_MANIFEST - path to manifest JSON file
# AVOCADO_STONE_BUILD_DIR - build output directory
# AVOCADO_STONE_DATA_DIR - stone data directory
# AVOCADO_SDK_PREFIX - SDK installation prefix (for nativesdk tools)

echo "=== Tegraflash Provisioning Script ==="
echo "Manifest: $AVOCADO_STONE_MANIFEST"
echo "Data dir: $AVOCADO_STONE_DATA_DIR"
echo "Build dir: $AVOCADO_STONE_BUILD_DIR"
echo "SDK prefix: ${AVOCADO_SDK_PREFIX:-<not set>}"

# SDK tegraflash tools location (used as fallback if tools tarball not in manifest)
TEGRAFLASH_TOOLS=""
if [ -n "${AVOCADO_SDK_PREFIX:-}" ]; then
    TEGRAFLASH_TOOLS="${AVOCADO_SDK_PREFIX}/sysroots/x86_64-avocadosdk-linux/usr/bin/tegraflash"
fi

# Read file names from manifest
# Runtime images
rootfs_file=$(jq -r '.storage_devices.rootdisk.images.rootfs // empty' "$AVOCADO_STONE_MANIFEST")
var_file=$(jq -r '.storage_devices.rootdisk.images.var // empty' "$AVOCADO_STONE_MANIFEST")
initramfs_file=$(jq -r '.storage_devices.rootdisk.images.initramfs // empty' "$AVOCADO_STONE_MANIFEST")

# Tegraflash-specific images
tegraflash_initramfs_file=$(jq -r '.storage_devices.rootdisk.images.tegraflash_initramfs // empty' "$AVOCADO_STONE_MANIFEST")
tegraflash_esp_file=$(jq -r '.storage_devices.rootdisk.images.tegraflash_esp // empty' "$AVOCADO_STONE_MANIFEST")
tegraflash_tos_file=$(jq -r '.storage_devices.rootdisk.images.tegraflash_tos // empty' "$AVOCADO_STONE_MANIFEST")
tegraflash_bsp_dir=$(jq -r '.storage_devices.rootdisk.images.tegraflash_bsp // empty' "$AVOCADO_STONE_MANIFEST")
tegraflash_tools_dir=$(jq -r '.storage_devices.rootdisk.images.tegraflash_tools // empty' "$AVOCADO_STONE_MANIFEST")

# Optional device tree files (may be in BSP or specified explicitly)
dtb_file=$(jq -r '.storage_devices.rootdisk.images.dtb // empty' "$AVOCADO_STONE_MANIFEST")
bpmp_dtb_file=$(jq -r '.storage_devices.rootdisk.images.bpmp_dtb // empty' "$AVOCADO_STONE_MANIFEST")

# Tegraflash overlay DTBOs (arrays of filenames) - for verification purposes
# The actual overlay values are in flashvars (from tegra-flashvars Yocto recipe)
# These manifest entries are used to verify that the overlay files exist in the BSP
tegraflash_overlays=$(jq -r '.storage_devices.rootdisk.tegraflash.overlays // [] | join(",")' "$AVOCADO_STONE_MANIFEST")
tegraflash_dce_overlays=$(jq -r '.storage_devices.rootdisk.tegraflash.dce_overlays // [] | join(",")' "$AVOCADO_STONE_MANIFEST")

echo "Runtime images from manifest:"
echo "  rootfs: $rootfs_file"
echo "  var: $var_file"
echo "  initramfs: $initramfs_file"
echo ""
echo "Tegraflash images from manifest:"
echo "  tegraflash_initramfs: $tegraflash_initramfs_file"
echo "  tegraflash_esp: $tegraflash_esp_file"
echo "  tegraflash_tos: $tegraflash_tos_file"
echo "  tegraflash_bsp: $tegraflash_bsp_dir"
echo "  tegraflash_tools: $tegraflash_tools_dir"
echo "  dtb: $dtb_file"
echo "  bpmp_dtb: $bpmp_dtb_file"
echo "  overlays: $tegraflash_overlays"
echo "  dce_overlays: $tegraflash_dce_overlays"

# Create build directory for tegraflash working area
build_dir="${AVOCADO_STONE_BUILD_DIR}/tegraflash"
rm -rf "$build_dir"
mkdir -p "$build_dir"

echo "Building tegraflash working directory: $build_dir"

# Copy BSP files from the directory (copied by stone create from the manifest)
# Stone now supports copying directories, so the BSP directory is in the stone output
if [ -n "$tegraflash_bsp_dir" ]; then
    bsp_source="${AVOCADO_STONE_DATA_DIR}/${tegraflash_bsp_dir}"
    if [ -d "$bsp_source" ]; then
        echo "Copying BSP files from $bsp_source"
        # Use "/." suffix to copy all files including hidden ones (like .env.initrd-flash)
        cp -a "$bsp_source"/. "$build_dir/"
        file_count=$(find "$build_dir" -type f | wc -l)
        echo "Copied $file_count files from BSP directory"
    else
        echo "ERROR: BSP directory not found: $bsp_source"
        echo "Contents of stone data directory:"
        ls -la "$AVOCADO_STONE_DATA_DIR"
        exit 1
    fi
else
    echo "ERROR: tegraflash_bsp not specified in manifest"
    exit 1
fi

# Copy tegraflash tools from the directory (copied by stone create from the manifest)
# This makes the stone output fully self-contained
if [ -n "$tegraflash_tools_dir" ]; then
    tools_source="${AVOCADO_STONE_DATA_DIR}/${tegraflash_tools_dir}"
    if [ -d "$tools_source" ]; then
        echo "Copying tegraflash tools from $tools_source"
        # Use "/." suffix to copy all files including hidden ones
        cp -a "$tools_source"/. "$build_dir/"
        tools_count=$(find "$build_dir" -type f -name "tegra*" -o -name "mk*" -o -name "*.py" | wc -l)
        echo "Copied tools (found $tools_count tegra/mk/python files)"
    else
        echo "ERROR: Tools directory not found: $tools_source"
        echo "Contents of stone data directory:"
        ls -la "$AVOCADO_STONE_DATA_DIR"
        exit 1
    fi
else
    # Fallback: try to copy from SDK if directory not specified
    if [ -n "$TEGRAFLASH_TOOLS" ] && [ -d "$TEGRAFLASH_TOOLS" ]; then
        echo "Copying tegraflash tools from SDK: $TEGRAFLASH_TOOLS"
        cp -a "$TEGRAFLASH_TOOLS"/. "$build_dir/"
    else
        echo "WARNING: Tegraflash tools not found in manifest or SDK"
        echo "Provisioning may fail without flash tools"
    fi
fi

# Copy image files to build directory
copy_image() {
    local src_path="$1"
    local dest_name="$2"
    
    if [ -n "$src_path" ]; then
        local full_src="${AVOCADO_STONE_DATA_DIR}/${src_path}"
        if [ -f "$full_src" ]; then
            echo "Copying $src_path -> $dest_name"
            cp "$full_src" "$build_dir/$dest_name"
        else
            echo "WARNING: File not found: $full_src"
        fi
    fi
}

# Copy runtime images
if [ -n "$rootfs_file" ]; then
    copy_image "$rootfs_file" "$(basename "$rootfs_file")"
fi

if [ -n "$var_file" ]; then
    copy_image "$var_file" "$(basename "$var_file")"
fi

if [ -n "$initramfs_file" ]; then
    copy_image "$initramfs_file" "$(basename "$initramfs_file")"
fi

# Copy tegraflash-specific images
# tegraflash_initramfs -> initrd-flash.img for RCM boot during flashing
# boot.img (runtime kernel+initramfs) is deployed by tegraflash-bsp recipe
if [ -n "$tegraflash_initramfs_file" ]; then
    copy_image "$tegraflash_initramfs_file" "initrd-flash.img"
fi

if [ -n "$tegraflash_esp_file" ]; then
    copy_image "$tegraflash_esp_file" "$(basename "$tegraflash_esp_file")"
    # Also copy to esp.img as expected by flash.xml ESP_FILE placeholder
    copy_image "$tegraflash_esp_file" "esp.img"
fi

if [ -n "$tegraflash_tos_file" ]; then
    copy_image "$tegraflash_tos_file" "$(basename "$tegraflash_tos_file")"
    # Also copy to tos-optee_t234.img as expected by flash.xml TOSFILE placeholder (for tegra234)
    # TODO: Make this SoC-agnostic using TOSIMGFILENAME from .env.initrd-flash
    copy_image "$tegraflash_tos_file" "tos-optee_t234.img"
fi

# Copy DTB files (if specified explicitly, otherwise they come from BSP)
if [ -n "$dtb_file" ]; then
    dtb_basename=$(basename "$dtb_file")
    copy_image "$dtb_file" "$dtb_basename"
    # Also copy to kernel_<dtb> as expected by some flash scripts
    copy_image "$dtb_file" "kernel_$dtb_basename"
fi

if [ -n "$bpmp_dtb_file" ]; then
    copy_image "$bpmp_dtb_file" "$(basename "$bpmp_dtb_file")"
fi

# Verify overlay DTBOs are present in build directory
# The overlay files are deployed by tegraflash-bsp recipe from staging
# OVERLAY_DTB_FILE and DCE_OVERLAY are defined in flashvars (from tegra-flashvars recipe)
if [ -n "$tegraflash_overlays" ]; then
    echo "Verifying overlay DTBOs from manifest..."
    IFS=',' read -ra overlay_array <<< "$tegraflash_overlays"
    for overlay in "${overlay_array[@]}"; do
        if [ -f "$build_dir/$overlay" ]; then
            echo "  Found: $overlay"
        else
            echo "  WARNING: Overlay DTBO not found: $overlay"
        fi
    done
fi

if [ -n "$tegraflash_dce_overlays" ]; then
    echo "Verifying DCE overlay DTBOs from manifest..."
    IFS=',' read -ra dce_overlay_array <<< "$tegraflash_dce_overlays"
    for overlay in "${dce_overlay_array[@]}"; do
        if [ -f "$build_dir/$overlay" ]; then
            echo "  Found: $overlay"
        else
            echo "  WARNING: DCE overlay DTBO not found: $overlay"
        fi
    done
fi

# Create temporary directory for cpp wrapper
temp_bin_dir=$(mktemp -d)
trap "rm -rf '$temp_bin_dir'" EXIT

# Create cpp wrapper using native SDK cpp
# Tegraflash needs a native cpp to preprocess DTS files on the host
SDK_HOST_CPP="${AVOCADO_SDK_ARCH:-$(uname -m)}-avocadosdk-linux-cpp"

cat > "$temp_bin_dir/cpp" << CPPWRAPPER
#!/bin/bash
exec ${SDK_HOST_CPP} "\$@"
CPPWRAPPER
chmod +x "$temp_bin_dir/cpp"

# Add temporary directory and tegraflash tools to PATH
export PATH="$temp_bin_dir:$build_dir:$PATH"

echo "Running initrd-flash script from build directory"

# Change to build directory and run initrd-flash script
cd "$build_dir"

if [ -x "./initrd-flash" ]; then
    ./initrd-flash --erase-nvme
else
    echo "ERROR: initrd-flash script not found or not executable"
    echo "Contents of build directory:"
    ls -la "$build_dir"
    exit 1
fi
