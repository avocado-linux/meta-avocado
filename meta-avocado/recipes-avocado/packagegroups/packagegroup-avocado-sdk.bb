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
  nativesdk-qemu \
  nativesdk-qemu-helper \
  nativesdk-bmaptool \
  nativesdk-python3-pip \
  nativesdk-make \
  nativesdk-cmake \
  nativesdk-squashfs-tools \
  ${@bb.utils.contains('SDK_TOOLCHAIN_LANGS', 'go', 'packagegroup-go-cross-canadian-${MACHINE}', '', d)} \
  ${@bb.utils.contains('SDK_TOOLCHAIN_LANGS', 'rust', 'packagegroup-rust-cross-canadian-${MACHINE}', '', d)} \
  ${@bb.utils.contains('DISTRO_FEATURES', 'wayland', 'nativesdk-wayland-tools nativesdk-wayland-dev', '', d)} \
  ${VIRTUAL-RUNTIME_avocado-sdk-metadata} \
"

SDK_SYSROOT_DEPENDS = " \
"

RDEPENDS:${PN} = " \
  ${SDK_TOOLCHAIN_DEPENDS} \
  ${SDK_SYSROOT_DEPENDS} \
"
