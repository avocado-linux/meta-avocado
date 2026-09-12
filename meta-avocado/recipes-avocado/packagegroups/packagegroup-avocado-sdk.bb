DESCRIPTION = "Packagegroup for Avocado SDK"
LICENSE = "Apache-2.0"

# No SPDX: do_create_package_spdx resolves every RDEPENDS' packages-staging
# document through SSTATE_ARCHS, which under allarch (SDK_ARCH = "none") can
# never name this group's SDK-arch deps. Metadata only - nothing to record.
inherit packagegroup avocado-nospdx
PACKAGES = "${PN}"

SDK_TOOLCHAIN_DEPENDS = " \
  avocado-sdk-bootstrap \
  avocado-sdk-toolchain \
"

SDK_SYSROOT_DEPENDS = " \
"

RDEPENDS:${PN} = " \
  ${SDK_TOOLCHAIN_DEPENDS} \
  ${SDK_SYSROOT_DEPENDS} \
"
