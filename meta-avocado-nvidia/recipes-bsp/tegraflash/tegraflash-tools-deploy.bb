DESCRIPTION = "Deploy tegraflash tools tarball for stone provisioning"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

COMPATIBLE_MACHINE = "(tegra)"

FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

# Only file:// fetches — wrynose no longer auto-creates ${S}, so set
# it explicitly to UNPACKDIR (where bitbake places file:// files).
S = "${UNPACKDIR}"

inherit deploy

# Depend on tegra-flashtools-native and tegra-helper-scripts-native to get the tools
DEPENDS = "tegra-flashtools-native tegra-helper-scripts-native"

# This recipe just deploys files, no compilation needed
do_compile[noexec] = "1"
do_install[noexec] = "1"

# Ensure native sysroot is populated before deploy
do_deploy[depends] += "tegra-flashtools-native:do_populate_sysroot tegra-helper-scripts-native:do_populate_sysroot"

# Deploy tegraflash tools directory for stone provisioning
# This allows the stone output directory to be fully self-contained
do_deploy() {
    install -d ${DEPLOYDIR}/tegraflash-tools
    
    # tegra-flashtools-native installs to ${bindir}/tegra-flash
    # tegra-helper-scripts-native also installs to the same location
    FLASH_SRC="${STAGING_BINDIR_NATIVE}/tegra-flash"
    
    bbnote "Looking for tegraflash tools at $FLASH_SRC"
    
    if [ -d "$FLASH_SRC" ]; then
        bbnote "Found tegra-flash tools at $FLASH_SRC"

        # Copy ALL files from the tegra-flash directory
        # This ensures we don't miss any required modules like tegrasign_v3_internal.py
        cp -a "$FLASH_SRC"/. ${DEPLOYDIR}/tegraflash-tools/

        # Log what was deployed
        file_count=$(find ${DEPLOYDIR}/tegraflash-tools -type f | wc -l)
        bbnote "Deployed tegraflash-tools directory with $file_count files"

        # NVIDIA's unified-flash python tools (under unified_flash/tools/flashtools/)
        # ship with absolute "#!/usr/bin/python3" shebangs. In the avocado SDK
        # those resolve to the host system's python3 (which lacks PyYAML and
        # the rest of our nativesdk python deps). Rewrite to "#!/usr/bin/env
        # python3" so PATH selects the nativesdk python at
        # ${AVOCADO_SDK_PREFIX}/usr/bin/python3, which has PyYAML via
        # nativesdk-python3-pyyaml (see avocado-sdk-target.bbappend).
        # Without this, Step 5 of the T264 unified flash flow dies with
        # ModuleNotFoundError: No module named 'yaml' inside create_bsp_images.py.
        find ${DEPLOYDIR}/tegraflash-tools -type f -name "*.py" \
            -exec sed -i "1s|^#!/usr/bin/python3$|#!/usr/bin/env python3|" {} +

        # NVIDIA's bootburn_t264_py library calls `udevadm` to resolve
        # /dev/bus/usb/<bus>/<dev> paths to canonical /sys/devices/... paths
        # for tegrarcm USB instance arguments. udevadm is unavailable in our
        # SDK container (no nativesdk-systemd; nativesdk-eudev would be the
        # heavy dep that gets us a stub binary anyway). Replace the udevadm
        # round-trip with sysfs-only equivalents using the per-USB-device
        # symlink at /sys/dev/char/<major>:<minor>. Mirrors the analogous
        # container-aware sysfs replacements already in initrd-flash.sh
        # (recipes-bsp/tegra-binaries/tegra-helper-scripts/initrd-flash.sh).
        ${PYTHON} ${UNPACKDIR}/strip-udevadm.py ${DEPLOYDIR}/tegraflash-tools

        # NVIDIA's wr_sh.sh wrapper script ships with a typo'd shebang
        # ("#/bin/sh" without the !) and mode 0644 (no +x). When pushed to
        # the device via adb push and exec'd as /tmp/wr_sh.sh, the missing
        # ! means exec() returns ENOEXEC and the shell-fallback only fires
        # if the file is +x. Net effect: every flashing call dies with
        # "Permission denied" (rc 126). Fix both at deploy time.
        wr_sh="${DEPLOYDIR}/tegraflash-tools/unified_flash/tools/flashtools/flash/wr_sh.sh"
        if [ -f "$wr_sh" ]; then
            sed -i '1{/^#!/!{s|^#/bin/sh|#!/bin/sh|}}' "$wr_sh"
            chmod 0755 "$wr_sh"
        fi
    else
        bbwarn "No tegraflash tools found in native sysroot at $FLASH_SRC"
    fi
}

SRC_URI += "file://strip-udevadm.py"

addtask deploy before do_build after do_compile

PACKAGE_ARCH = "${MACHINE_ARCH}"
