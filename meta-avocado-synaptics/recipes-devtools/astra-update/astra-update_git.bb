SUMMARY = "Synaptics Astra USB flashing utility (astra-update, astra-boot)"
DESCRIPTION = "Host-side USB provisioning tool for Synaptics Astra Machina \
devices. Built from source so it can run inside containers without depending \
on the host's libudev."
HOMEPAGE = "https://github.com/synaptics-astra/astra-update"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://LICENSE;md5=86d3f3a95c324c9479bd8986968f4327"

PV = "1.0.6"
SRCREV = "a4f5d5c4e86bbc45e8a5329f175df4fbd489811f"
SRC_URI = "git://github.com/synaptics-astra/astra-update.git;branch=main;protocol=https \
           file://0001-remove-udev-link.patch \
           file://0002-use-system-deps.patch \
"

S = "${WORKDIR}/git"

DEPENDS = "libusb1 yaml-cpp cxxopts indicators"

inherit cmake pkgconfig

BBCLASSEXTEND = "nativesdk"
