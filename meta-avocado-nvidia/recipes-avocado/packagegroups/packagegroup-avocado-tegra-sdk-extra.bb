DESCRIPTION = "Packagegroup for inclusion in extra Avocado SDK extras for tegra"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

# nativesdk packages for host-side tooling
SDK_TOOLCHAIN_TEGRA = " \
  nativesdk-packagegroup-cuda-sdk-host \
  nativesdk-tegraflash-tools \
"

# Target sysroot packages for building out-of-tree kernel modules
# that depend on nvidia-kernel-oot headers/symbols
SDK_SYSROOT_TEGRA = " \
  nvidia-kernel-oot-devsrc \
"

RDEPENDS:${PN} = " \
  ${SDK_TOOLCHAIN_TEGRA} \
  ${SDK_SYSROOT_TEGRA} \
"
