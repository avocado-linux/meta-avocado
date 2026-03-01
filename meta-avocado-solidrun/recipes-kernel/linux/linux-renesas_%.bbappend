FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI:append = " file://avocado-core.cfg \
        file://panfrost.cfg \
        file://0001-dts-renesas-enable-mali-gpu.patch"

