FILESEXTRAPATHS:prepend := "${THISDIR}/${BPN}:"

SRC_URI:append = " file://external-flash.xml file://internal-flash-emmc.xml"

# Upstream sets S = "${UNPACKDIR}" but does not override B, so B == UNPACKDIR.
# Our PARTITION_FILE_EXTERNAL points at ${UNPACKDIR}/external-flash.xml, and
# do_compile copies it to relative path "external-flash.xml" (= ${B}/external-flash.xml),
# which would be the same file. Match the sibling tegra-binaries recipes
# (tegra-flashtools, tegra-flashvars, etc.) and use a separate build dir.
B = "${WORKDIR}/build"

PARTITION_FILE_EXTERNAL = "${UNPACKDIR}/external-flash.xml"

# Process and install the eMMC layout variant for "build once, provision to any media"
do_compile:append() {
    copy_in_flash_layout ${UNPACKDIR}/internal-flash-emmc.xml ${B}/internal-flash-emmc.xml
}

do_install:append() {
    install -m 0644 ${B}/internal-flash-emmc.xml ${D}${datadir}/tegraflash/
}
