SUMMARY = "Avocado debug tweaks extension package"
DESCRIPTION = "RPM package containing the debug tweaks extension for Avocado OS"
LICENSE = "Apache-2.0"

require avocado-extension.bb

# Version should match the extension version
PV = "1.0"

# Define package name explicitly to match extension naming convention
PN = "avocado-extension-debug-tweaks"

# Source image details
EXT_ID = "debug-tweaks"
EXTIMG = "avocado-image-debug-tweaks"
EXTIMG_NAME = "${EXTIMG}-${EXTIMG_MACHINE}.rootfs"

# Provide virtual name for dependency resolution
RPROVIDES:${PN} = "avocado-extension-debug-tweaks"
