DESCRIPTION = "Avocado feature group: printing daemon, filters, and PDF tools"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

RDEPENDS:${PN} = " \
  cups \
  cups-filters \
  ghostscript \
  poppler \
  qpdf \
"
