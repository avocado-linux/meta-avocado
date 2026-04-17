DESCRIPTION = "Packagegroup for Raspberry Pi rootfs - packages needed for runtime"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

RDEPENDS:${PN} = " \
  avocado-uboot-env \
"
