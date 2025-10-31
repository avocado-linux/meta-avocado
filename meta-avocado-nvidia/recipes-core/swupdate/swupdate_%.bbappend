FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

# disable u-boot for nvidia targets
SRC_URI += "file://disable_uboot.cfg"

# make sure we have nvbootctrl
RDEPENDS:${PN} += "tegra-redundant-boot-base"
