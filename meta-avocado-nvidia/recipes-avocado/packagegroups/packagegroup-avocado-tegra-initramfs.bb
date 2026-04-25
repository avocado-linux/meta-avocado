DESCRIPTION = "Packagegroup for inclusion in Avocado tegra initramfs images"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

RDEPENDS:${PN} = " \
    avocado-tegra-init \
    tegra-firmware-xusb \
"
