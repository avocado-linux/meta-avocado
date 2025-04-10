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
EXT_ID ?= "undefined"
EXT_VERSION ?= "1"

# Extension installation directories
SYSEXT_DESTDIR = "/usr/lib/extensions"

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

# Build tar.bz2 for extension deployment
IMAGE_FSTYPES += "tar.bz2"

do_rootfs_wicenv[noexec] = "1"
do_image_wic[noexec] = "1"
