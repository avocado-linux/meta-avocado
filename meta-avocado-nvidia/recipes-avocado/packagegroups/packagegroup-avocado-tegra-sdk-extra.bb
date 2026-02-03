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

SDK_SYSROOT_TEGRA = " \
"

RDEPENDS:${PN} = " \
  ${SDK_TOOLCHAIN_TEGRA} \
  ${SDK_SYSROOT_TEGRA} \
"
