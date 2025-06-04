DESCRIPTION = "Packagegroup for Avocado SDK"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

SDK_TOOLCHAIN_DEPENDS = " \
  avocado-sdk-toolchain \
  nativesdk-avocado-pkg-rootfs \
  nativesdk-avocado-pkg-initramfs \
  nativesdk-avocado-pkg-images \
  ${VIRTUAL-RUNTIME_avocado-sdk-metadata} \
"

SDK_SYSROOT_DEPENDS = " \
"

RDEPENDS:${PN} = " \
  ${SDK_TOOLCHAIN_DEPENDS} \
  ${SDK_SYSROOT_DEPENDS} \
"
