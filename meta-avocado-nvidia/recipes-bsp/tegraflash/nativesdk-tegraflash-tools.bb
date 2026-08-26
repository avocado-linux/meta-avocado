DESCRIPTION = "Tegraflash tools for SDK"
LICENSE = "MIT & Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

FILESEXTRAPATHS:prepend := "${THISDIR}/files:${THISDIR}/../tegra-binaries/tegra-helper-scripts:"

inherit nativesdk

# Flash tools and helper scripts (custom overrides of upstream scripts)
# Scripts not listed here (find-jetson-usb, nvflashxmlparse, nvbct-config) come
# from the native sysroot via tegra-helper-scripts-native.
SRC_URI = "\
    file://initrd-flash.sh \
    file://make-sdcard.sh \
    file://tegra234-flash-helper.sh \
"

S = "${UNPACKDIR}"

# We need access to the flash tools from tegra-binaries
# These are built as native and need to be copied to SDK
# Use explicit task dependency since nativesdk can't access native sysroot via DEPENDS
do_install[depends] += "tegra-flashtools-native:do_populate_sysroot tegra-helper-scripts-native:do_populate_sysroot"

RDEPENDS:${PN} = "\
    nativesdk-python3 \
    nativesdk-python3-pyyaml \
    nativesdk-bash \
    nativesdk-coreutils \
    nativesdk-util-linux \
    nativesdk-gptfdisk \
"

TEGRAFLASH_BINDIR = "${SDKPATHNATIVE}${bindir_nativesdk}/tegraflash"

# Path to native staging directory for accessing native-built tools
STAGING_DIR_NATIVE_BINDIR = "${STAGING_DIR_NATIVE}${bindir_native}"

do_install() {
    install -d ${D}${TEGRAFLASH_BINDIR}
    
    # Install avocado-customized helper scripts
    install -m 0755 ${UNPACKDIR}/initrd-flash.sh ${D}${TEGRAFLASH_BINDIR}/initrd-flash
    install -m 0755 ${UNPACKDIR}/make-sdcard.sh ${D}${TEGRAFLASH_BINDIR}/make-sdcard
    install -m 0755 ${UNPACKDIR}/tegra234-flash-helper.sh ${D}${TEGRAFLASH_BINDIR}/tegra234-flash-helper.sh
    
    # Determine flash tools source directory from native staging
    # Use STAGING_DIR_NATIVE since nativesdk can't access native tools via STAGING_BINDIR_NATIVE
    # tegra-flashtools-native installs to ${bindir}/tegra-flash
    FLASH_SRC="${STAGING_DIR_NATIVE}${bindir_native}/tegra-flash"
    
    bbnote "Looking for tegraflash tools at $FLASH_SRC"
    
    if [ ! -d "$FLASH_SRC" ]; then
        bbfatal "No tegraflash tools found at $FLASH_SRC"
    fi
    
    if [ -d "$FLASH_SRC" ]; then
        # Copy flash tools from native sysroot
        # These are x86_64 binaries that work on the SDK host
        for tool in tegrabct_v2 tegradevflash_v2 tegrahost_v2 tegraparser_v2 \
                    tegrarcm_v2 tegrasign_v2 chkbdinfo mkgpt mksparse mkbootimg \
                    nv_smd_generator tegrakeyhash; do
            if [ -f "$FLASH_SRC/$tool" ]; then
                install -m 0755 "$FLASH_SRC/$tool" ${D}${TEGRAFLASH_BINDIR}/
            fi
        done
        
        # Copy Python scripts from native sysroot
        for script in tegraflash.py tegraflash_internal.py gen_tos_part_img.py \
                      BUP_generator.py rollback_parser.py sw_memcfg_overlay.pl; do
            if [ -f "$FLASH_SRC/$script" ]; then
                install -m 0755 "$FLASH_SRC/$script" ${D}${TEGRAFLASH_BINDIR}/
            fi
        done
        
        # Copy function libraries
        for func in l4t_bup_gen.func odmsign.func; do
            if [ -f "$FLASH_SRC/$func" ]; then
                install -m 0644 "$FLASH_SRC/$func" ${D}${TEGRAFLASH_BINDIR}/
            fi
        done
        
        # Copy upstream's unified flash helper from the native sysroot; it is the
        # FLASH_HELPER on tegra264/Thor (tegra234 uses our copy installed above).
        for helper in tegra-flash-helper.sh; do
            if [ -f "$FLASH_SRC/$helper" ]; then
                install -m 0755 "$FLASH_SRC/$helper" ${D}${TEGRAFLASH_BINDIR}/
            fi
        done
        
        # Copy pkc tools if available
        if [ -d "$FLASH_SRC/pkc" ]; then
            install -d ${D}${TEGRAFLASH_BINDIR}/pkc
            for tool in "$FLASH_SRC"/pkc/*; do
                if [ -f "$tool" ]; then
                    install -m 0755 "$tool" ${D}${TEGRAFLASH_BINDIR}/pkc/
                fi
            done
        fi
    else
        bbwarn "No tegraflash tools found in native sysroot"
    fi
}

FILES:${PN} = "${TEGRAFLASH_BINDIR}"
# Skip QA checks for pre-built NVIDIA binaries:
# - already-stripped: binaries are pre-stripped
# - file-rdeps: may have dependencies not in SDK
# - arch: NVIDIA provides 32-bit x86 binaries in some versions
INSANE_SKIP:${PN} = "already-stripped file-rdeps arch"
INSANE_SKIP:${PN}-dbg = "arch"

# Prebuilt x86_64 ELFs ship inside this package and are executed on aarch64 SDK
# hosts via host-kernel binfmt_misc + qemu-user-static (configured on the build
# host, not the SDK container). Suppress auto-generated dependency Requires so
# rpmdeps doesn't emit unsatisfiable libc.so.6 symbol-version Requires -- the
# ELFs' GLIBC_2.2.5 / GLIBC_2.3 / libm.so.6 needs don't exist on aarch64, which
# only ships GLIBC_2.17+.
#
# EXCLUDE_FROM_SHLIBS disables the shlibs scanner; SKIP_FILEDEPS disables the
# per-file rpmdeps ELF scan (FILERDEPENDS) -- both paths emit Requires.
EXCLUDE_FROM_SHLIBS = "1"
SKIP_FILEDEPS:${PN} = "1"

# Inhibit debug/strip processing - these are prebuilt x86_64 binaries
# that cannot be processed by the aarch64 cross-objcopy
INHIBIT_PACKAGE_DEBUG_SPLIT = "1"
INHIBIT_PACKAGE_STRIP = "1"
