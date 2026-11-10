FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"
FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}/env:"

SRC_URI:append = " \
  file://avocado.cfg \
  file://avocado-env-mmc.cfg \
  file://fastboot.cfg \
"

# A/B boot (BOOTVARS = "ubootenv"): a redundant environment in the eMMC that
# avocadoctl flips with fw_setenv, and env/${MACHINE}.txt (mkenvimage, via
# meta-avocado-distro's u-boot-env.inc) carrying the boot flow that reads it.
# Stone writes that image at provision time.
MKENVIMAGE_EXTRA_ARGS:bootvars-ubootenv = "-r"

# USB gadget (fastboot) on RZ/V2N: SolidRun's legacy USBHS port only knew
# R-Car Gen3 / RZ/G2L addresses.
SRC_URI:append:rzv2n-sr-som = " \
  file://0001-usb-gadget-rcar-support-the-RZ-V2H-P-and-RZ-V2N-USBH.patch \
  file://0002-usb-gadget-rcar-set-ep-desc-in-usbhsg_ep_enable.patch \
"

# meta-rz-drpai V1.50 renamed its ether-setting patch to
# 0001-add-ether-setting-RZV2N.patch, so meta-rzv2n's SRC_URI:remove of the
# old name no longer matches. The patch targets Renesas's U-Boot, not
# SolidRun's fork, and fails do_patch there.
SRC_URI:remove:rzv2n-sr-som = "file://0001-add-ether-setting-RZV2N.patch"

# meta-arm's u-boot_%.bbappend adds a devupstream (mainline denx master)
# variant to every U-Boot recipe; its PV also matches meta-rz-bsp's
# PREFERRED_VERSION_u-boot = "2024.07%", and bitbake picked it over the
# SolidRun fork. Drop the variant, as meta-avocado-qcom does for its kernel.
BBCLASSEXTEND:remove = "devupstream:target"
