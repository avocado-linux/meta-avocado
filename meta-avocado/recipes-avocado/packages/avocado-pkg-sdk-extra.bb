SUMMARY = "Builds the Avocado SDK Extras for the platform"
LICENSE = "Apache-2.0"

inherit image-packages-only

IMAGE_INSTALL = " \
  packagegroup-avocado-sdk-extra \
  nativesdk-packagegroup-qt5-toolchain-host \
  ${SDK_PKG_EXTRA_INSTALL} \
"
