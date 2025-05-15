SUMMARY = "Builds the Avocado SDK for the platform"
LICENSE = "Apache-2.0"

inherit image-packages-only

SDK_PKG_EXTRA_INSTALL ??= ""
IMAGE_INSTALL = "packagegroup-avocado-sdk ${SDK_PKG_EXTRA_INSTALL}"
