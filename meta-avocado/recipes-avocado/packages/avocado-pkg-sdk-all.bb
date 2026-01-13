SUMMARY = "Builds the full Avocado SDK with all packages for the platform"
LICENSE = "Apache-2.0"

PV = "${SDK_VERSION}"

inherit image-packages-only

IMAGE_INSTALL = "packagegroup-avocado-sdk-all"

# Disable license tasks - dependencies handle their own licensing
do_populate_lic[noexec] = "1"
do_populate_lic_deploy[noexec] = "1"
