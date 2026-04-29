FILESEXTRAPATHS:prepend := "${THISDIR}/${BPN}:"

SRC_URI:append = " file://external-flash.xml file://internal-flash-emmc.xml"

PARTITION_FILE_EXTERNAL = "${UNPACKDIR}/external-flash.xml"

# Process and install the eMMC layout variant for "build once, provision to any media"
do_compile:append() {
    copy_in_flash_layout ${UNPACKDIR}/internal-flash-emmc.xml ${B}/internal-flash-emmc.xml
}

do_install:append() {
    install -m 0644 ${B}/internal-flash-emmc.xml ${D}${datadir}/tegraflash/
}
