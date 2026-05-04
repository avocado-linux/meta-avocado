DESCRIPTION = "Packagegroup for STM32MP2 extra packages"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

RDEPENDS:${PN} = " \
    kernel-modules \
    linux-firmware-bcm43xx \
    iw \
    wpa-supplicant \
    wireless-regdb \
    bluez5 \
    bluez5-obex \
    pciutils \
    pciutils-ids \
    usbutils \
    libgpiod \
    libgpiod-tools \
    ethtool \
"
