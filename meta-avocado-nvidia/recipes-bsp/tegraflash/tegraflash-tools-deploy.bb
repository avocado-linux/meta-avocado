DESCRIPTION = "Deploy tegraflash tools tarball for stone provisioning"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

COMPATIBLE_MACHINE = "(tegra)"

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
    else
        bbwarn "No tegraflash tools found in native sysroot at $FLASH_SRC"
    fi
}

addtask deploy before do_build after do_compile

PACKAGE_ARCH = "${MACHINE_ARCH}"
