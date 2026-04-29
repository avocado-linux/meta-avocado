SUMMARY = "Synaptics Astra USB boot firmware images"
DESCRIPTION = "Per-SoC USB boot firmware blobs (sl1620/sl1640/sl1680/vs640) \
used by astra-update to bring the device up over USB before flashing eMMC/SPI."
HOMEPAGE = "https://github.com/synaptics-astra/usb-tool"
LICENSE = "CLOSED"

PV = "1.0.6+git"
SRCREV = "c054106f4b113858039155d495f7837c66247ca4"
SRC_URI = "git://github.com/synaptics-astra/usb-tool.git;branch=main;protocol=https"


do_configure[noexec] = "1"
do_compile[noexec] = "1"

do_install() {
    install -d ${D}${datadir}/astra-update
    cp -r ${S}/astra-usbboot-images ${D}${datadir}/astra-update/
}

FILES:${PN} = "${datadir}/astra-update"

# Firmware blobs are pre-stripped/non-ELF; arch QA doesn't apply.
INSANE_SKIP:${PN} += "arch already-stripped"

BBCLASSEXTEND = "nativesdk"
