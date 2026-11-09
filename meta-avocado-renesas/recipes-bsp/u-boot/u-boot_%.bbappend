FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

SRC_URI:append = " \
  file://avocado.cfg \
  file://env-nowhere.cfg \
  file://fastboot.cfg \
"

# USB gadget (fastboot) on RZ/V2N: SolidRun's legacy USBHS port only knew
# R-Car Gen3 / RZ/G2L addresses.
SRC_URI:append:rzv2n-sr-som = " \
  file://0001-usb-gadget-rcar-support-the-RZ-V2H-P-and-RZ-V2N-USBH.patch \
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
