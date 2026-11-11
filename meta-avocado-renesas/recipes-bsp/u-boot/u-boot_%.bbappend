FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"
FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}/env:"

SRC_URI:append = " \
  file://avocado.cfg \
  file://avocado-env-mmc.cfg \
  file://usb-gadget.cfg \
"

# A/B boot (BOOTVARS = "ubootenv"): a redundant environment in the eMMC holding
# the slot state, which avocadoctl flips with fw_setenv. env/${MACHINE}.txt
# seeds it (mkenvimage, via meta-avocado-distro's u-boot-env.inc) and stone
# writes that image at provision time. The boot flow that reads it is compiled
# into U-Boot from avocado-rzv2n-sr-som.env (below), not taken from this file.
MKENVIMAGE_EXTRA_ARGS:bootvars-ubootenv = "-r"

# USB gadget (UMS provisioning, the fastboot fallback) on RZ/V2N: SolidRun's
# legacy USBHS port only knew R-Car Gen3 / RZ/G2L addresses.
SRC_URI:append:rzv2n-sr-som = " \
  file://0001-usb-gadget-rcar-support-the-RZ-V2H-P-and-RZ-V2N-USBH.patch \
  file://0002-usb-gadget-rcar-set-ep-desc-in-usbhsg_ep_enable.patch \
  file://0003-rzv2n-solidrun-permit-list-for-the-saved-environment.patch \
  file://env-compiled-in.cfg \
  file://avocado-rzv2n-sr-som.env \
"

# env-compiled-in.cfg: CONFIG_ENV_SOURCE_FILE="avocado" resolves to
# board/$(SYS_VENDOR)/$(SYS_BOARD)/avocado.env = board/solidrun/rzv2n here. A
# missing file builds an EMPTY default environment without an error, so fail
# loudly if SolidRun moves the board directory.
do_configure:prepend:rzv2n-sr-som() {
    if [ ! -d ${S}/board/solidrun/rzv2n ]; then
        bbfatal "board/solidrun/rzv2n is absent from ${S}: the compiled-in Avocado environment (env-compiled-in.cfg) has nowhere to go"
    fi
    # U-Boot's env2string keeps '#' and blank lines and glues them onto the
    # neighbouring variable (one became a variable with an empty name, and the
    # whole default environment failed to import with EINVAL): drop them.
    sed -e '/^#/d' -e '/^[[:space:]]*$/d' ${UNPACKDIR}/avocado-rzv2n-sr-som.env \
        >${S}/board/solidrun/rzv2n/avocado.env
    # U-Boot's hush treats a single quote as a quote even inside double
    # quotes: one in a message swallowed the rest of the command, and bootcmd
    # stopped at boot with "syntax error". Nothing here needs one.
    if grep -n "'" ${S}/board/solidrun/rzv2n/avocado.env; then
        bbfatal "avocado-rzv2n-sr-som.env: a single quote in a command line breaks U-Boot's hush parser"
    fi
}

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
