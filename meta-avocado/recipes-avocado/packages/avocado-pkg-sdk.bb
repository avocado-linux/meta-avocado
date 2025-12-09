SUMMARY = "Builds the Avocado SDK for the platform"
LICENSE = "Apache-2.0"

PV = "${SDK_VERSION}"

inherit image-packages-only

IMAGE_INSTALL = "packagegroup-avocado-sdk packagegroup-avocado-sdk-all ${SDK_TOOLCHAIN_EXTRA_INSTALL}"
