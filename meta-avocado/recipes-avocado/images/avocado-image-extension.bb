DESCRIPTION = "Avocado system and configuration extension image"
LICENSE = "Apache-2.0"

inherit image

# Configure image basics
IMAGE_FEATURES = ""
IMAGE_LINGUAS = ""

# Include requested packages
IMAGE_INSTALL = "${EXTENSION_PACKAGES}"

# Default value - override in extensions
EXTENSION_PACKAGES ?= ""

# Set the extension version and ID
EXT_ID ?= "debug-tweaks"
EXT_VERSION ?= "1"

# Extension installation directories
SYSEXT_DESTDIR = "/usr/lib/extensions"
CONFEXT_DESTDIR = "/usr/lib/confexts"

do_rootfs[vardeps] += "EXT_ID EXT_VERSION"

# Create the extension metadata and structure
ROOTFS_POSTPROCESS_COMMAND += "create_extension_metadata; "

create_extension_metadata() {
    # Create the extension metadata directory
    install -d ${IMAGE_ROOTFS}/usr/lib/extension-release.d/
    
    # Create the extension-release file with appropriate metadata
    cat > ${IMAGE_ROOTFS}/usr/lib/extension-release.d/extension-release.${EXT_ID} << EOF
ID=${DISTRO}
VERSION_ID=${DISTRO_VERSION}
SYSEXT_LEVEL=1
EXTENSION_ID=${EXT_ID}
EXTENSION_VERSION=${EXT_VERSION}
EXTENSION_COMBINED=1
EOF
    
    # Get the machine ID from the base system for compatibility if available
    if [ -f ${STAGING_DIR_TARGET}/usr/lib/os-release ]; then
        grep "^MACHINE_ID=" ${STAGING_DIR_TARGET}/usr/lib/os-release >> ${IMAGE_ROOTFS}/usr/lib/extension-release.d/extension-release.${EXT_ID} || true
    fi
}

# Build tar.bz2 for direct extension deployment
IMAGE_FSTYPES += "tar.bz2"

# Installation script to be included in packages that use this extension
install_extension() {
    # Create the destination directories
    install -d ${D}${SYSEXT_DESTDIR}
    install -d ${D}${CONFEXT_DESTDIR}
    
    # Copy the extension file
    install -m 0644 ${DEPLOY_DIR_IMAGE}/${IMAGE_NAME}.rootfs.tar.bz2 ${D}${SYSEXT_DESTDIR}/${EXT_ID}.raw
    
    # Create a symlink for the configuration extension if needed
    if [ -d ${IMAGE_ROOTFS}/etc ]; then
        ln -sf ${SYSEXT_DESTDIR}/${EXT_ID}.raw ${D}${CONFEXT_DESTDIR}/${EXT_ID}.raw
    fi
}