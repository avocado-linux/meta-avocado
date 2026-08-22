FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"
FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}/env:"

# The UUU tag goes on the boot partition. For 8+, the boot partition image
# is imx-boot, so disable UUU-tagging here
UUU_BOOTLOADER:mx8-generic-bsp = ""
UUU_BOOTLOADER:mx9-generic-bsp = ""

SRC_URI:append:class-target = " \
  file://avocado.cfg \
  file://env-mmc.cfg \
"

# The FRDM defconfigs enable EFI capsule authentication, whose ESL step shells
# out to a host tool no recipe here provides, so do_compile fails on a clean
# workspace whether or not signing is on. Not gated on any feature for that
# reason. See the fragment for the full account.
#
# SRC_URI is the whole mechanism - do NOT add a cat line to do_configure:append
# below for this fragment. UBOOT_DEFCONFIG expands to the literal ['sd'] (its
# `.split((',', 1)[0])` is `.split(',')`, which returns a list), so every cat
# line writes to a path named ['sd'] and the real defconfig is never touched.
# These fragments reach .config via cml1.bbclass's merge_config.sh over
# SRC_URI's file://*.cfg entries instead.
#
# imx93-frdm and imx91-frdm only, matching the equivalent already carried on
# imx93-ahab-secure-boot so the two branches converge rather than diverge on a
# file in the boot path. avocado-imx95-frdm's defconfig carries the same symbol
# and is likely broken identically, but it is not built or booted here and is
# left alone rather than changed unverified.
SRC_URI:append:imx93-frdm = " file://no-efi-capsule-auth.cfg"
SRC_URI:append:imx91-frdm = " file://no-efi-capsule-auth.cfg"

# disable-unused-vendor-features.cfg turns off NXP stock defconfig defaults
# Avocado never uses and this board's tree cannot actually build - see the
# fragment's own header comment. Machine override, not python: this is a
# single unconditional per-machine fragment, not a two-axis machine+feature
# gate, so bitbake's native override stacking (:avocado-imx93-frdm:class-target)
# is sufficient.
SRC_URI:append:avocado-imx93-frdm = " file://disable-unused-vendor-features.cfg"

MKENVIMAGE_EXTRA_ARGS = "-r"

UBOOT_DEFCONFIG = "${@'${UBOOT_CONFIG}'.split((',', 1)[0])}"

do_configure:append:class-target () {
  cat ${UNPACKDIR}/avocado.cfg >> ${S}/configs/${UBOOT_DEFCONFIG}
  cat ${UNPACKDIR}/env-mmc.cfg >> ${S}/configs/${UBOOT_DEFCONFIG}
}

do_configure:append:avocado-imx93-frdm:class-target () {
  cat ${UNPACKDIR}/disable-unused-vendor-features.cfg >> ${S}/configs/${UBOOT_DEFCONFIG}
}

require recipes-bsp/u-boot/u-boot-env.inc
