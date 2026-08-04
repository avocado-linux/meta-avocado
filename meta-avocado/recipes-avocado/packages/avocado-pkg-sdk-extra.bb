SUMMARY = "Builds the Avocado SDK Extras for the platform"
LICENSE = "Apache-2.0"

PV = "${SDK_VERSION}"

inherit image-packages-only

IMAGE_INSTALL = " \
  packagegroup-avocado-sdk-extra \
  ${@bb.utils.contains('AVOCADO_FEATURE_GROUPS', 'qt', 'nativesdk-packagegroup-qt5-toolchain-host', '', d)} \
  ${SDK_PKG_EXTRA_INSTALL} \
"
