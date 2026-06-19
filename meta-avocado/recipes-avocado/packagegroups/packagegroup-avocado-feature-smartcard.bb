DESCRIPTION = "Avocado feature group: smartcard daemon and drivers"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

RDEPENDS:${PN} = " \
  ccid \
  pcsc-lite \
  pcsc-lite-lib \
"
