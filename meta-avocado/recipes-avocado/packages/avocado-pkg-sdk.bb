SUMMARY = "Builds the Avocado SDK for the platform"
LICENSE = "Apache-2.0"

PV = "${SDK_VERSION}"

inherit image-packages-only

IMAGE_INSTALL = "packagegroup-avocado-sdk packagegroup-avocado-sdk-all ${SDK_TOOLCHAIN_EXTRA_INSTALL}"

# Disable license tasks - dependencies handle their own licensing
do_populate_lic[noexec] = "1"
do_populate_lic_deploy[noexec] = "1"
