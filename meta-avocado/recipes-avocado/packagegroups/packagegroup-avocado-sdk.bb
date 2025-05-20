DESCRIPTION = "Packagegroup for Avocado SDK"
LICENSE = "Apache-2.0"

inherit packagegroup

SDK_TOOLCHAIN_DEPENDS = " \
  avocado-sdk-toolchain \
  nativesdk-avocado-pkg-bootfiles \
  nativesdk-avocado-pkg-img-initramfs \
  nativesdk-avocado-pkg-img-rootfs \
  nativesdk-avocado-pkg-img-var \
  nativesdk-bmaptool \
  ${VIRTUAL-RUNTIME_avocado-sdk-metadata} \
"

SDK_SYSROOT_DEPENDS = " \
"

RDEPENDS:${PN} = " \
  ${SDK_TOOLCHAIN_DEPENDS} \
  ${SDK_SYSROOT_DEPENDS} \
"
