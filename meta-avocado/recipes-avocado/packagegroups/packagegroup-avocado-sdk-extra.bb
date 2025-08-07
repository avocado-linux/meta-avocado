DESCRIPTION = "Packagegroup for Avocado SDK Extra"
LICENSE = "Apache-2.0"

inherit packagegroup
PACKAGES = "${PN}"

SDK_TOOLCHAIN_DEPENDS = " \
  nativesdk-bmaptool \
  nativesdk-fwup \
  nativesdk-ganesha \
  nativesdk-jq \
  nativesdk-mkfat \
  nativesdk-python3-pip \
  nativesdk-qemu \
  nativesdk-qemu-helper \
  nativesdk-strace \
  packagegroup-rust-cross-canadian-${MACHINE} \
  ${@bb.utils.contains('DISTRO_FEATURES', 'wayland', 'nativesdk-wayland-tools nativesdk-wayland-dev', '', d)} \
"

SDK_SYSROOT_DEPENDS = " \
  ${@multilib_pkg_extend(d, 'packagegroup-core-standalone-sdk-target')} \
  ${@multilib_pkg_extend(d, 'libstd-rs')} \
"

RDEPENDS:${PN} = " \
  ${SDK_TOOLCHAIN_DEPENDS} \
  ${SDK_SYSROOT_DEPENDS} \
"
