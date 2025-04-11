DESCRIPTION = "Avocado debug tweaks extension for development"
LICENSE = "Apache-2.0"

require avocado-image-extension.bb

EXT_ID = "debug-tweaks"
EXT_VERSION = "1"

# Include debug packages and tools
EXTENSION_PACKAGES = " \
    strace \
    ltrace \
    lsof \
    vim \
"

EXTRA_IMAGE_FEATURES += "debug-tweaks ssh-server-openssh"
