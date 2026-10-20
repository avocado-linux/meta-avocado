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

# NVIDIA's tegraflash_impl_t264.py uses `break` inside `finally` blocks
# (see lines ~2174 / ~2193). Python 3.14 (PEP 765) emits SyntaxWarning for
# this and Python 3.16 will reject it as a SyntaxError. The warnings are
# noise in our provisioning output today; remove this when NVIDIA fixes
# upstream or we localise a patch in tegraflash-tools-deploy.
export PYTHONWARNINGS="${PYTHONWARNINGS:-ignore::SyntaxWarning}"

# Pre-warm adb. NVIDIA's flash_bsp_images.py runs `adb start-server` once and
# treats failure as fatal. On a fresh SDK container, the first start-server
# call triggers ~/.android/adbkey RSA keygen which can race the daemon ACK
# timeout (so first call returns "failed to start daemon" even though it
# eventually succeeds). Run start-server here twice to absorb the first-run
# init race so the actual flashing call later sees an already-running daemon.
# Wrapped in a subshell with relaxed flags + outer `|| true` so this
# best-effort warmup cannot abort the script under set -e/-u/pipefail.
(
    set +eu
    _adb_bin="$(command -v adb 2>/dev/null)" || true
    # tegraflash-tools/ is the BSP source dir (always present at script start);
    # _build/tegraflash/ doesn't exist yet here (it's populated later by cp -a).
    if [ -z "${_adb_bin:-}" ] && [ -n "${AVOCADO_STONE_DATA_DIR:-}" ]; then
        _adb_bin="$(find "$AVOCADO_STONE_DATA_DIR/tegraflash-tools" -name adb -type f 2>/dev/null | head -1)" || true
    fi
    if [ -n "${_adb_bin:-}" ]; then
        mkdir -p "${HOME:-/root}/.android" 2>/dev/null
        "$_adb_bin" start-server >/dev/null 2>&1
        "$_adb_bin" start-server >/dev/null 2>&1
    fi
) || true

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
tegraflash_carrier_bsp_dir=$(jq -r '.storage_devices.rootdisk.images.tegraflash_carrier_bsp // empty' "$AVOCADO_STONE_MANIFEST")

# Optional device tree files (may be in BSP or specified explicitly)
dtb_file=$(jq -r '.storage_devices.rootdisk.images.dtb // empty' "$AVOCADO_STONE_MANIFEST")
bpmp_dtb_file=$(jq -r '.storage_devices.rootdisk.images.bpmp_dtb // empty' "$AVOCADO_STONE_MANIFEST")

# Tegraflash overlay DTBOs (arrays of filenames) - for verification purposes
# The actual overlay values are in flashvars (from tegra-flashvars Yocto recipe)
# These manifest entries are used to verify that the overlay files exist in the BSP
tegraflash_overlays=$(jq -r '.storage_devices.rootdisk.tegraflash.overlays // [] | join(",")' "$AVOCADO_STONE_MANIFEST")
tegraflash_dce_overlays=$(jq -r '.storage_devices.rootdisk.tegraflash.dce_overlays // [] | join(",")' "$AVOCADO_STONE_MANIFEST")

# Block device the SD card enumerates as on this module - a board property, so
# the board's manifest is where it is declared. Consumed by the sd) branch of
# the boot-media case below.
tegraflash_sd_device=$(jq -r '.storage_devices.rootdisk.tegraflash.sd_device // empty' "$AVOCADO_STONE_MANIFEST")

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
echo "  tegraflash_carrier_bsp: $tegraflash_carrier_bsp_dir"
echo "  dtb: $dtb_file"
echo "  bpmp_dtb: $bpmp_dtb_file"
echo "  overlays: $tegraflash_overlays"
echo "  dce_overlays: $tegraflash_dce_overlays"
echo "  sd_device: ${tegraflash_sd_device:-<not declared>}"

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

# ─── Carrier-BSP overlay ─────────────────────────────────────────────
# SOM-style targets (jetson-orin-nx, jetson-orin-nano, jetson-agx-orin)
# layer carrier customization via a `carrier-bsp/` slot in the stone
# bundle. avocado-cli composes the slot from the active runtime's BSP
# extensions (`stone_include_paths`); the Yocto-side tegraflash-bsp
# ships only an empty `.placeholder` stub, so any extension files win.
#
# Two-step apply:
#   1. Flatten carrier-bsp/* into build_dir/, clobbering any same-named
#      MACHINE-baked file (e.g. a carrier-modified DTB shadows the
#      stock DevKit DTB). This is the filename-shadowing path that
#      works without any knobs.
#   2. If carrier-bsp/carrier.env declares CARRIER_FV_<NAME>=<value>
#      or CARRIER_ENV_<NAME>=<value>, rewrite the corresponding
#      <NAME>= line in flashvars / .env.initrd-flash. This lets a
#      carrier ship files under any name (including renamed-with-suffix
#      variants like `*-adv.dtb`) and redirect the flash flow at them.
if [ -n "$tegraflash_carrier_bsp_dir" ]; then
    carrier_source="${AVOCADO_STONE_DATA_DIR}/${tegraflash_carrier_bsp_dir}"
    if [ -d "$carrier_source" ]; then
        carrier_files=$(find "$carrier_source" -maxdepth 1 -type f ! -name '.placeholder' | wc -l)
        if [ "$carrier_files" -gt 0 ]; then
            echo "Carrier-BSP overlay: $carrier_source ($carrier_files file(s))"
            # cp -a "$src"/. preserves attrs and copies hidden files,
            # matching the BSP/tools copy pattern above.
            cp -a "$carrier_source"/. "$build_dir/"

            carrier_env="$build_dir/carrier.env"
            if [ -f "$carrier_env" ]; then
                # Print the human-readable label first so the active
                # carrier is obvious in provision logs.
                _label=$(grep -E '^CARRIER_LABEL=' "$carrier_env" | head -1 \
                            | sed -E 's/^CARRIER_LABEL=//; s/^"//; s/"$//')
                if [ -n "$_label" ]; then
                    echo "  Carrier: $_label"
                fi

                # Apply CARRIER_FV_/CARRIER_ENV_ rewrites. Each knob
                # patches an existing <NAME>= line; if <NAME> isn't in
                # the target file we WARN rather than append, since a
                # spurious new line can break the flash flow.
                while IFS= read -r line; do
                    key="${line%%=*}"
                    val="${line#*=}"
                    # Strip surrounding double or single quotes.
                    val="${val#\"}"; val="${val%\"}"
                    val="${val#\'}"; val="${val%\'}"
                    # Escape sed delimiter occurrences (defensive — '|'
                    # is unlikely in DTB filenames or ODMDATA values).
                    esc_val="${val//|/\\|}"

                    case "$key" in
                        CARRIER_FV_*)
                            fv_key="${key#CARRIER_FV_}"
                            if [ -f "$build_dir/flashvars" ] && \
                               grep -qE "^${fv_key}=" "$build_dir/flashvars"; then
                                sed -i -E "s|^(${fv_key})=.*|\\1=\"${esc_val}\"|" \
                                    "$build_dir/flashvars"
                                echo "  flashvars: ${fv_key}=${val}"
                            else
                                echo "  WARNING: CARRIER_FV_${fv_key} target not found in flashvars; skipped"
                            fi
                            ;;
                        CARRIER_ENV_*)
                            env_key="${key#CARRIER_ENV_}"
                            if [ -f "$build_dir/.env.initrd-flash" ] && \
                               grep -qE "^${env_key}=" "$build_dir/.env.initrd-flash"; then
                                sed -i -E "s|^(${env_key})=.*|\\1=\"${esc_val}\"|" \
                                    "$build_dir/.env.initrd-flash"
                                echo "  .env.initrd-flash: ${env_key}=${val}"
                            else
                                echo "  WARNING: CARRIER_ENV_${env_key} target not found in .env.initrd-flash; skipped"
                            fi
                            ;;
                        # CARRIER_LABEL handled above.
                        # CARRIER_SIGNED_* reserved for Phase 2 (signed flash).
                    esac
                done < <(grep -E '^[[:space:]]*CARRIER_(FV|ENV)_' "$carrier_env")
            fi
        else
            echo "Carrier-BSP slot empty (no overrides; using MACHINE-baked defaults)"
        fi
    else
        echo "Carrier-BSP source not found: $carrier_source (skipping overlay)"
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
    # Resolve the SoC-specific TOS image filename from .env.initrd-flash
    # (TOSIMGFILENAME = tos-optee_t234.img | tos-optee_t264.img | tos-optee.img).
    # Fall back to the tegra234 name for older BSPs that don't emit the var.
    tos_dst="tos-optee_t234.img"
    env_file="$build_dir/.env.initrd-flash"
    if [ -f "$env_file" ]; then
        env_tos=$(grep -E '^TOSIMGFILENAME=' "$env_file" | tail -1 | cut -d= -f2- | tr -d '"')
        [ -n "$env_tos" ] && tos_dst="$env_tos"
    fi
    copy_image "$tegraflash_tos_file" "$tos_dst"
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

# Tegraflash needs a host-native cpp to preprocess DTS files.
# The nativesdk cpp may not be installed, so fall back to the
# cross-compiler cpp which works fine for preprocessing (target
# architecture is irrelevant for text preprocessing).
SDK_HOST_CPP=""
_nativesdk_cpp="${AVOCADO_SDK_ARCH:-$(uname -m)}-avocadosdk-linux-cpp"
if command -v "$_nativesdk_cpp" >/dev/null 2>&1; then
    SDK_HOST_CPP="$_nativesdk_cpp"
elif [ -n "${CC:-}" ]; then
    _cc_bin="${CC%% *}"
    _cross_cpp="${_cc_bin/gcc/cpp}"
    if command -v "$_cross_cpp" >/dev/null 2>&1; then
        SDK_HOST_CPP="$_cross_cpp"
    fi
fi
if [ -z "$SDK_HOST_CPP" ] && command -v cpp >/dev/null 2>&1; then
    SDK_HOST_CPP="cpp"
fi
if [ -z "$SDK_HOST_CPP" ]; then
    echo "ERROR: No C preprocessor (cpp) found in PATH"
    echo "Tegraflash requires cpp for DTS preprocessing."
    echo "Ensure the SDK toolchain is properly configured."
    exit 1
fi

cat > "$temp_bin_dir/cpp" << CPPWRAPPER
#!/bin/bash
exec ${SDK_HOST_CPP} "\$@"
CPPWRAPPER
chmod +x "$temp_bin_dir/cpp"

# Add temporary directory and tegraflash tools to PATH
export PATH="$temp_bin_dir:$build_dir:$PATH"

# Rootfs PARTUUIDs for this flash. Empty means "not pinned", which keeps the
# pre-existing behaviour end to end: the layout below keeps its APPUUID
# placeholders, the flashing tool picks its own GUIDs, and the initrd falls back
# to locating APP by PARTLABEL.
#
# Pinning matters because PARTLABEL does not identify a disk. A board carrying a
# provisioned SD card AND a provisioned NVMe has two partitions labelled APP with
# equally valid contents, and the initrd takes whichever the kernel enumerated
# first - the SD card, since PCIe enumeration finishes about two seconds after
# the SD controller is up. Naming the PARTUUID makes the rootfs a property of
# what was provisioned rather than of probe timing.
#
# Generated per flash rather than fixed per medium: a constant published in this
# repo would be identical on every board, so removable media carrying that
# PARTUUID could present itself as the rootfs, and changing one later would
# orphan every board already flashed with the old value.
app_partuuid=""
app_b_partuuid=""

# When avocado-cli has staged a kernel Image from the resolver-pinned rootfs
# sysroot, repack boot.img on the host so the booted kernel matches the
# resolver's kernel.version pin. Without this, the prebuilt boot.img copied
# from the BSP dir (default-mc kernel) wins and the runtime kernel mismatches
# the rootfs modules. Falls back to the prebuilt boot.img when the env var is
# unset (legacy / no kernel pin).
app_partuuid=""
app_b_partuuid=""
if [ -n "${AVOCADO_PROVISION_KERNEL_IMAGE:-}" ]; then
    if [ ! -f "$AVOCADO_PROVISION_KERNEL_IMAGE" ]; then
        echo "ERROR: AVOCADO_PROVISION_KERNEL_IMAGE=$AVOCADO_PROVISION_KERNEL_IMAGE not found"
        exit 1
    fi
    initramfs_in_build="$build_dir/$(basename "$initramfs_file")"
    if [ ! -f "$initramfs_in_build" ]; then
        echo "ERROR: initramfs cpio not staged at $initramfs_in_build"
        exit 1
    fi
    # Name the rootfs this run is about to write, so the initrd stops
    # rediscovering it. Both slots are carried because the same boot.img is
    # written to A_kernel and B_kernel, so one command line has to serve
    # whichever slot nvbootctrl later selects; avocado-tegra-init picks between
    # them using the slot it already resolves from BootChainOsCurrent.
    #
    # The pins are appended through AVOCADO_KERNEL_CMDLINE_EXTRA, so
    # avocado-tegra-bootimg keeps the BSP's KERNEL_ARGS and the project's
    # kernel.cmdline / cmdline_extra and only adds these two arguments.
    app_partuuid=$(tr 'a-f' 'A-F' </proc/sys/kernel/random/uuid)
    app_b_partuuid=$(tr 'a-f' 'A-F' </proc/sys/kernel/random/uuid)
    AVOCADO_KERNEL_CMDLINE_EXTRA="${AVOCADO_KERNEL_CMDLINE_EXTRA:+$AVOCADO_KERNEL_CMDLINE_EXTRA }avocado.root_partuuid=$app_partuuid avocado.root_partuuid_b=$app_b_partuuid"
    export AVOCADO_KERNEL_CMDLINE_EXTRA
    # The command line comes from the prebuilt boot.img header, composed with
    # the project's kernel.cmdline / cmdline_extra; see avocado-tegra-bootimg.
    # An empty line is silently fatal: L4TLauncher falls back to the stock
    # NVIDIA bootargs in the kernel DTB, which on tegra264 point the console
    # at a tegra-utc instance that is not wired out.
    echo "Packing boot.img from kernel ${AVOCADO_PROVISION_KERNEL_VERSION:-?} (Image=$AVOCADO_PROVISION_KERNEL_IMAGE)"
    avocado-tegra-bootimg "$(command -v mkbootimg)" "$build_dir/boot.img" \
        "$AVOCADO_PROVISION_KERNEL_IMAGE" "$initramfs_in_build" "$build_dir/boot.img" || exit 1
    echo "boot.img repacked at provision time"
else
    if [ -n "${AVOCADO_KERNEL_CMDLINE:-}${AVOCADO_KERNEL_CMDLINE_EXTRA:-}" ]; then
        echo "ERROR: kernel.cmdline / cmdline_extra is set, but no kernel Image was staged"
        echo "       (AVOCADO_PROVISION_KERNEL_IMAGE) to repack boot.img with it."
        exit 1
    fi
    echo "AVOCADO_PROVISION_KERNEL_IMAGE not set — using prebuilt boot.img from BSP"
    echo "WARNING: the prebuilt boot.img names no rootfs PARTUUID. The initrd takes"
    echo "         APP on the disk UEFI booted from (BootCurrent), or the only APP"
    echo "         when the boot entry names no disk. With no boot signal and two"
    echo "         or more provisioned disks it refuses to guess and stops."
fi

# Check if any NVIDIA device is in RCM mode (vendor 0955).
# All Jetson boards in RCM use NVIDIA vendor ID 0955 with varying product IDs.
check_rcm() {
    lsusb -d 0955: 2>/dev/null | grep -qi "APX\|rcm" && return 0
    # Fallback: check known RCM product IDs if grep doesn't match description
    for pid in 7018 7418 7019 7e19 7023 7223 7323 7423 7523 7623; do
        lsusb -d 0955:$pid >/dev/null 2>&1 && return 0
    done
    return 1
}

if check_rcm; then
    echo "Device already in RCM mode"
else
    boardctl_target="${BOARDCTL_TARGET:-}"
    boardctl_attempted=0

    # Only attempt boardctl if BOARDCTL_TARGET is explicitly set — this indicates
    # the board has TOPO debug hardware. Without it, skip straight to waiting.
    if [ -n "$boardctl_target" ] && command -v boardctl >/dev/null 2>&1; then
        echo "Device not in RCM mode, attempting recovery via boardctl (target=$boardctl_target)..."
        boardctl_args="-t $boardctl_target"
        boardctl_serial="${BOARDCTL_SERIAL:-}"
        [ -n "$boardctl_serial" ] && boardctl_args="$boardctl_args -s $boardctl_serial"
        # boardctl may fail if device/debugger isn't connected — catch and fall through
        set +e
        boardctl $boardctl_args recovery 2>&1
        boardctl_rc=$?
        set -e
        if [ $boardctl_rc -eq 0 ]; then
            boardctl_attempted=1
        else
            echo "WARNING: boardctl failed (exit $boardctl_rc) — device may not be connected or TOPO not detected"
            echo "Falling back to waiting for manual recovery..."
        fi
    fi

    # Wait for device to enter RCM mode (either from boardctl or manual button press)
    if [ $boardctl_attempted -eq 1 ]; then
        echo "Waiting for device to enter RCM mode..."
    else
        echo "Please put device into recovery mode (hold recovery button, press reset)..."
    fi
    for i in $(seq 1 60); do
        check_rcm && break
        sleep 1
    done
    if ! check_rcm; then
        echo "ERROR: Device did not enter RCM mode (waited 60s)"
        exit 1
    fi
    echo "Device in RCM mode"
fi

# --- Determine boot media from provision profile name ---
boot_media="nvme"
case "${AVOCADO_PROVISION_PROFILE:-tegraflash}" in
    tegraflash|tegraflash-nvme)
        boot_media="nvme"
        ;;
    tegraflash-mmc|tegraflash-emmc)
        boot_media="emmc"
        ;;
    tegraflash-sd)
        boot_media="sd"
        ;;
    *)
        echo "WARNING: Unknown tegraflash profile '${AVOCADO_PROVISION_PROFILE}', defaulting to nvme"
        ;;
esac

echo "Boot media target: $boot_media (profile: ${AVOCADO_PROVISION_PROFILE:-tegraflash})"

# --- Build flash arguments from profile + env vars ---
flash_args=""

# Boot media determines default erase behavior
case "$boot_media" in
    nvme)
        sed -i \
            -e 's/^BOOTDEV=.*/BOOTDEV="nvme0n1p1"/' \
            -e 's/^ROOTFS_DEVICE=.*/ROOTFS_DEVICE="nvme0n1"/' \
            -e 's/^EXTERNAL_ROOTFS_DRIVE=.*/EXTERNAL_ROOTFS_DRIVE=1/' \
            "$build_dir/.env.initrd-flash"
        flash_args="--erase-nvme"
        ;;
    emmc)
        sed -i \
            -e 's/^BOOTDEV=.*/BOOTDEV="mmcblk0p1"/' \
            -e 's/^ROOTFS_DEVICE=.*/ROOTFS_DEVICE="mmcblk0"/' \
            -e 's/^EXTERNAL_ROOTFS_DRIVE=.*/EXTERNAL_ROOTFS_DRIVE=1/' \
            "$build_dir/.env.initrd-flash"
        # flash.xml.in must remain as SPI boot layout (used for signing).
        # Swap external-flash.xml.in to the eMMC rootfs layout instead.
        if [ -f "$build_dir/internal-flash-emmc.xml" ]; then
            cp "$build_dir/internal-flash-emmc.xml" "$build_dir/external-flash.xml.in"
            echo "Using eMMC flash layout (internal-flash-emmc.xml -> external-flash.xml.in)"
        else
            echo "ERROR: internal-flash-emmc.xml not found in BSP"
            exit 1
        fi
        ;;
    sd)
        # Which MMC device the card enumerates as is a property of the module,
        # so it is declared per board rather than defaulted here. An eMMC-less
        # module instantiates only the SD controller and the card is the first
        # MMC device (3400000.mmc -> mmc0 -> mmcblk0); a module carrying eMMC
        # puts eMMC on mmc0 and the card on mmc1, which is what the BSP's
        # generic/cfg/flash_t234_qspi_sd*.xml assume. There is no default that
        # is right for both, and getting it wrong writes at the other device -
        # on an eMMC-bearing module, at internal storage.
        sd_device="${AVOCADO_PROVISION_SD_DEVICE:-$tegraflash_sd_device}"
        if [ -z "$sd_device" ]; then
            echo "ERROR: no SD card device declared for this board." >&2
            echo "       Add .storage_devices.rootdisk.tegraflash.sd_device to" >&2
            echo "       $AVOCADO_STONE_MANIFEST - mmcblk0 on a module without" >&2
            echo "       eMMC, the next MMC index on one that has it - or set" >&2
            echo "       AVOCADO_PROVISION_SD_DEVICE for a one-off run." >&2
            exit 1
        fi
        # Validate before it reaches sed's replacement text. The natural
        # mistake is a /dev path, which turns the substitution into
        # s/^BOOTDEV=.*/BOOTDEV="/dev/mmcblk1p1"/ and dies at "unknown option
        # to `s'"; an & would silently insert the matched text instead. The
        # accepted form is the one initrd-flash's own export path matches.
        if [[ ! "$sd_device" =~ ^mmcblk[0-9]+$ ]]; then
            echo "ERROR: SD card device '$sd_device' is not a bare mmcblkN name." >&2
            echo "       Expected e.g. mmcblk0, not a /dev path and not a" >&2
            echo "       partition. Set AVOCADO_PROVISION_SD_DEVICE or the" >&2
            echo "       manifest's tegraflash.sd_device accordingly." >&2
            exit 1
        fi
        echo "SD card device: $sd_device"
        sed -i \
            -e "s/^BOOTDEV=.*/BOOTDEV=\"${sd_device}p1\"/" \
            -e "s/^ROOTFS_DEVICE=.*/ROOTFS_DEVICE=\"${sd_device}\"/" \
            -e 's/^EXTERNAL_ROOTFS_DRIVE=.*/EXTERNAL_ROOTFS_DRIVE=1/' \
            "$build_dir/.env.initrd-flash"
        ;;
esac

# Boot the medium this flash targets. The flash resets the UEFI variable store,
# and on an empty store the firmware sorts BootOrder once by DefaultBootPriority
# (edk2-nvidia PlatformBootOrderLib), never again. L4TConfiguration.dtbo ships
# "usb,nvme,emmc,sd,ufs", so a provisioned SD card loses to any NVMe or USB disk
# still carrying an OS. Put the target class first; the rest keep their order.
l4t_conf_dtbo="$build_dir/L4TConfiguration.dtbo"
boot_priority_node=/fragment@0/__overlay__/firmware/uefi/variables/gNVIDIATokenSpaceGuid/DefaultBootPriority
stock_priority=$(fdtget -t s "$l4t_conf_dtbo" "$boot_priority_node" data) || {
    echo "ERROR: cannot read DefaultBootPriority from $l4t_conf_dtbo" >&2
    exit 1
}
boot_priority=$boot_media
IFS=, read -ra stock_classes <<<"$stock_priority"
for class in "${stock_classes[@]}"; do
    [ "$class" = "$boot_media" ] || boot_priority="$boot_priority,$class"
done
# Edit a private copy: a link would carry the change back into the staged BSP.
if [ -L "$l4t_conf_dtbo" ]; then
    cp --remove-destination "$(readlink -f "$l4t_conf_dtbo")" "$l4t_conf_dtbo" || exit 1
fi
fdtput -t s "$l4t_conf_dtbo" "$boot_priority_node" data "$boot_priority" || {
    echo "ERROR: cannot set DefaultBootPriority in $l4t_conf_dtbo" >&2
    exit 1
}
[ "$(fdtget -t s "$l4t_conf_dtbo" "$boot_priority_node" data)" = "$boot_priority" ] || {
    echo "ERROR: DefaultBootPriority did not take in $l4t_conf_dtbo" >&2
    exit 1
}
echo "UEFI DefaultBootPriority: $boot_priority (was $stock_priority)"

# Write the rootfs PARTUUIDs the command line names into the layout the flash is
# about to apply. Runs after the media case because the eMMC branch swaps the
# whole layout file in, and substituting before that would fill the copy we then
# discard.
if [ -n "$app_partuuid" ]; then
    layout_xml="$build_dir/external-flash.xml.in"
    if [ ! -f "$layout_xml" ]; then
        echo "ERROR: $layout_xml not found; cannot pin the rootfs PARTUUIDs." >&2
        exit 1
    fi
    # APPUUID_b contains APPUUID, so a bare grep for the latter is satisfied by
    # the former and would pass a layout that pins only slot B. Match each
    # exactly. A missing placeholder means this is not the templated layout we
    # expect - flashing on would write GUIDs that disagree with the command line
    # we just baked, giving an initrd that cannot find its root.
    for pattern in 'APPUUID_b' 'APPUUID[^_]'; do
        if ! grep -q "$pattern" "$layout_xml"; then
            echo "ERROR: $layout_xml has no $pattern placeholder." >&2
            echo "       tegraflash-bsp.bb is expected to leave these for us to" >&2
            echo "       fill; if it blanks them again, the command line names a" >&2
            echo "       rootfs PARTUUID this layout will never produce." >&2
            exit 1
        fi
    done
    sed -i \
        -e "s/APPUUID_b/$app_b_partuuid/g" \
        -e "s/APPUUID/$app_partuuid/g" \
        "$layout_xml"
    if grep -q 'APPUUID' "$layout_xml"; then
        echo "ERROR: APPUUID placeholder survived substitution in $layout_xml." >&2
        exit 1
    fi
    echo "Rootfs PARTUUID: $app_partuuid (slot A), $app_b_partuuid (slot B)"
else
    # Nothing pinned (prebuilt boot.img): blank the placeholders, as
    # tegraflash-bsp.bb did before it started keeping them. Left in, sgdisk
    # accepts the literal "APPUUID" and writes an all-zero PARTUUID to both
    # rootfs slots instead of generating one.
    layout_xml="$build_dir/external-flash.xml.in"
    [ ! -f "$layout_xml" ] || sed -i -e 's/APPUUID_b//g' -e 's/APPUUID//g' "$layout_xml"
fi

# Composable env var flags (override defaults from profile)
[ "${ERASE_NVME:-0}" = "1" ] && flash_args="$flash_args --erase-nvme"
[ "${ERASE_EMMC:-0}" = "1" ] && flash_args="$flash_args --erase-emmc"
[ "${ERASE_ONLY:-0}" = "1" ] && flash_args="$flash_args --erase-only"

# Deduplicate --erase-nvme if profile already added it
flash_args=$(echo "$flash_args" | tr ' ' '\n' | sort -u | tr '\n' ' ')

echo "Flash arguments: $flash_args"
echo "Running initrd-flash script from build directory"

# Change to build directory and run initrd-flash script
cd "$build_dir"

if [ -x "./initrd-flash" ]; then
    ./initrd-flash $flash_args
else
    echo "ERROR: initrd-flash script not found or not executable"
    echo "Contents of build directory:"
    ls -la "$build_dir"
    exit 1
fi
