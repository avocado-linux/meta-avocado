# Add -devsrc packages for nvidia-kernel-oot modules
#
# This bbappend creates -devsrc packages that contain development sources
# (headers, Module.symvers, Makefiles, etc.) needed for building out-of-tree
# kernel modules that depend on nvidia-kernel-oot modules.
#
# This is similar to how kernel-devsrc works for the main kernel.
# Users can install nvidia-kernel-oot-devsrc into the target-dev sysroot
# to compile their own modules that depend on nvidia headers/symbols.
#
# Usage example (in extension compile script):
#   KBUILD_EXTRA_SYMBOLS="${OECORE_TARGET_SYSROOT}/usr/src/nvidia-oot/Module.symvers"
#   make -C ${KDIR} M=$(pwd) KBUILD_EXTRA_SYMBOLS=${KBUILD_EXTRA_SYMBOLS} modules

# Add -devsrc packages
PACKAGES =+ "${PN}-devsrc ${PN}-display-devsrc ${PN}-cameras-devsrc ${PN}-base-devsrc"

# Installation path for nvidia-kernel-oot sources
# Use a unique path to avoid any conflicts with kernel-devsrc (/usr/src/kernel)
NVIDIA_OOT_DEVSRC_PATH = "/usr/src/nvidia-oot"

# Main devsrc package includes all development sources
# This is the comprehensive package for building any module that depends on nvidia-kernel-oot
FILES:${PN}-devsrc = "${NVIDIA_OOT_DEVSRC_PATH}"

# Category-specific devsrc packages (depend on main devsrc)
# These are convenience packages for users who only need specific subsystem headers
FILES:${PN}-display-devsrc = ""
FILES:${PN}-cameras-devsrc = ""
FILES:${PN}-base-devsrc = ""

ALLOW_EMPTY:${PN}-display-devsrc = "1"
ALLOW_EMPTY:${PN}-cameras-devsrc = "1"
ALLOW_EMPTY:${PN}-base-devsrc = "1"

RDEPENDS:${PN}-display-devsrc = "${PN}-devsrc"
RDEPENDS:${PN}-cameras-devsrc = "${PN}-devsrc"
RDEPENDS:${PN}-base-devsrc = "${PN}-devsrc"

# The devsrc package depends on kernel-devsrc since you need both to build modules
RDEPENDS:${PN}-devsrc = "kernel-devsrc"

do_install:append() {
    # Create nvidia-kernel-oot devsrc directory structure
    # This mirrors what kernel-devsrc does but for nvidia out-of-tree modules
    install -d ${D}${NVIDIA_OOT_DEVSRC_PATH}

    # Copy Module.symvers - essential for building modules that use nvidia symbols
    # This file contains all exported symbols from nvidia-kernel-oot modules
    # Users need to pass KBUILD_EXTRA_SYMBOLS pointing to this file when building
    if [ -f "${D}${includedir}/${BPN}/Module.symvers" ]; then
        install -m 0644 ${D}${includedir}/${BPN}/Module.symvers ${D}${NVIDIA_OOT_DEVSRC_PATH}/
    elif [ -f "${B}/Module.symvers" ]; then
        install -m 0644 ${B}/Module.symvers ${D}${NVIDIA_OOT_DEVSRC_PATH}/
    fi

    # Copy all include headers needed for building dependent modules
    if [ -d "${S}/nvidia-oot/include" ]; then
        mkdir -p ${D}${NVIDIA_OOT_DEVSRC_PATH}/include
        cp -R ${S}/nvidia-oot/include/* ${D}${NVIDIA_OOT_DEVSRC_PATH}/include/
    fi

    # Copy Makefiles and Kconfig files for reference
    if [ -f "${S}/Makefile" ]; then
        install -m 0644 ${S}/Makefile ${D}${NVIDIA_OOT_DEVSRC_PATH}/
    fi

    # Copy nvidia-oot directory structure (headers, configs) preserving tree
    if [ -d "${S}/nvidia-oot" ]; then
        (
            cd ${S}
            find nvidia-oot -name "*.h" -print0 | while IFS= read -r -d '' file; do
                install -D -m 0644 "$file" "${D}${NVIDIA_OOT_DEVSRC_PATH}/$file"
            done
            find nvidia-oot -name "Makefile" -print0 | while IFS= read -r -d '' file; do
                install -D -m 0644 "$file" "${D}${NVIDIA_OOT_DEVSRC_PATH}/$file"
            done
            find nvidia-oot -name "Kconfig*" -print0 | while IFS= read -r -d '' file; do
                install -D -m 0644 "$file" "${D}${NVIDIA_OOT_DEVSRC_PATH}/$file"
            done
        )
    fi

    # Copy nvdisplay headers if present (for modules depending on display subsystem)
    if [ -d "${S}/nvdisplay" ]; then
        (
            cd ${S}
            find nvdisplay -name "*.h" -print0 | while IFS= read -r -d '' file; do
                install -D -m 0644 "$file" "${D}${NVIDIA_OOT_DEVSRC_PATH}/$file"
            done
            find nvdisplay -name "Makefile" -print0 | while IFS= read -r -d '' file; do
                install -D -m 0644 "$file" "${D}${NVIDIA_OOT_DEVSRC_PATH}/$file"
            done
        )
    fi

    # Copy kernel-devicetree sources for dtb building
    if [ -d "${S}/kernel-devicetree" ]; then
        (
            cd ${S}
            find kernel-devicetree -name "*.h" -print0 | while IFS= read -r -d '' file; do
                install -D -m 0644 "$file" "${D}${NVIDIA_OOT_DEVSRC_PATH}/$file"
            done
            find kernel-devicetree -name "*.dtsi" -print0 | while IFS= read -r -d '' file; do
                install -D -m 0644 "$file" "${D}${NVIDIA_OOT_DEVSRC_PATH}/$file"
            done
            find kernel-devicetree -name "*.dts" -print0 | while IFS= read -r -d '' file; do
                install -D -m 0644 "$file" "${D}${NVIDIA_OOT_DEVSRC_PATH}/$file"
            done
        )
    fi

    # Create a version file for SDK compatibility checking
    echo "${PV}" > ${D}${NVIDIA_OOT_DEVSRC_PATH}/.nvidia-kernel-oot-version

    # Fix ownership
    chown -R root:root ${D}${NVIDIA_OOT_DEVSRC_PATH}
}

# Make the -devsrc package installable in target sysroot similar to kernel-devsrc
INSANE_SKIP:${PN}-devsrc = "arch"
