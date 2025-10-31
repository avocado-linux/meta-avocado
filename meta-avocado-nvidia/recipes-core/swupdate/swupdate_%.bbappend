FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

# disable u-boot for nvidia targets
SRC_URI += "file://disable_uboot.cfg"
