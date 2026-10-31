DESCRIPTION = "Packagegroup for the Avocado browsers feature group"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

# A machine family can drop a browser it cannot build: qcom-base.inc sets
# BROWSER_PACKAGES:qcom = "" (chromium 146 needs wayland >= 1.24).
BROWSER_PACKAGES ?= "${@bb.utils.contains('DISTRO_FEATURES', 'opengl wayland', 'chromium-ozone-wayland', '', d)}"

RDEPENDS:${PN} = "${BROWSER_PACKAGES}"
