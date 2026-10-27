FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"
FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}/env:"

# A/B boot for the U-Boot environment boards (BOOTVARS = "ubootenv"): a
# redundant environment on the boot MMC that avocadoctl flips with fw_setenv,
# and env/${MACHINE}.txt (mkenvimage, via meta-avocado-distro's
# u-boot-env.inc) carrying the boot flow that reads it. Stone writes that
# image at provision time.
SRC_URI:append:bootvars-ubootenv = " file://avocado-env-mmc.cfg"
MKENVIMAGE_EXTRA_ARGS:bootvars-ubootenv = "-r"

# The R5S's USB 3.0/MASK port as a gadget in U-Boot, for rockusb provisioning
# of the eMMC or the microSD from a running U-Boot (the sd-usb profile).
SRC_URI:append:nanopi-r5s = " \
    file://avocado-nanopi-r5s-otg.dtsi \
    file://avocado-nanopi-r5s-otg.cfg \
"
do_configure:prepend:nanopi-r5s() {
    cp ${UNPACKDIR}/avocado-nanopi-r5s-otg.dtsi ${S}/arch/arm/dts/
}
