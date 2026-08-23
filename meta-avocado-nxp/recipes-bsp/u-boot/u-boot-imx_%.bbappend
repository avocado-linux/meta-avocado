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

# fit.cfg enables base FIT container support (CONFIG_FIT) unconditionally on
# avocado-imx93-frdm. The boot partition manifest (stone-imx93-frdm.json) and
# the U-Boot env boot command (env/avocado-imx93-frdm.txt) are both static
# per-machine files with no bitbake conditional mechanism, and both already
# bootm a single FIT unconditionally - so U-Boot on this machine must always
# be able to parse a FIT, signed or not. Every other NXP board is unaffected.
#
# SRC_URI is the whole mechanism. cml1.bbclass's do_configure runs
# merge_config.sh over every file://*.cfg in SRC_URI, straight from the layer
# path - that is what puts these symbols in .config. Do NOT add a `cat` line
# into do_configure:append for a new fragment: UBOOT_DEFCONFIG below expands to
# the literal ['sd'] (its `.split((',', 1)[0])` is `.split(',')`, which returns
# a list), so every cat line in this file appends to a path named `['sd']` and
# the real imx93_11x11_frdm_defconfig is never touched. Confirmed from
# temp/run.do_configure and log.do_configure on a real build. A fragment added
# only via a cat line therefore reaches nothing, silently - which for a
# verification Kconfig means shipping a bootloader that enforces nothing.
SRC_URI:append:avocado-imx93-frdm = " file://fit.cfg"

# fit-verify.cfg enables U-Boot FIT signature verification. It is NOT
# unconditional like fit.cfg above: it is only meaningful on
# avocado-imx93-frdm (the only machine this change wires a FIT signing key
# for) and only when the customer has opted in via the 'verified-boot'
# DISTRO_FEATURES token, so every other NXP board and every frdm build
# without the feature build exactly as before (still gets an unsigned FIT
# via fit.cfg above, but no signature enforcement).
#
# The same gate also embeds the FIT public key into U-Boot's own control DTB,
# so the running bootloader carries its own trust anchor rather than reading
# the key from writable storage at runtime (spec: "the verification key is
# not modifiable from the running system"). u-boot.inc already unconditionally
# inherits OE-core's uboot-sign.bbclass, so setting UBOOT_SIGN_ENABLE plus the
# same UBOOT_SIGN_KEYDIR/UBOOT_SIGN_KEYNAME="FIT" pair task 3.1 wires for the
# kernel-fitimage side is enough: uboot-sign's do_uboot_assemble_fitimage task
# (added unconditionally by u-boot.inc, gated internally on UBOOT_SIGN_ENABLE)
# runs mkimage -f auto-conf against AVOCADO_SB_KEYS_DIR/FIT.crt and embeds the
# PUBLIC half only into u-boot.dtb before it is concatenated into the final
# u-boot binary - the private FIT.key never leaves the build host. This board
# already builds with CONFIG_OF_SEPARATE=y, the precondition uboot-sign.bbclass
# documents for this embedding step, so no CONFIG_DEFAULT_DEVICE_TREE/binman
# fallback is needed here. DEPENDS on sb-keys is added under the same gate so
# FIT.crt exists in AVOCADO_SB_KEYS_DIR before this recipe's fitimage-assemble
# task runs.
python () {
    if d.getVar('MACHINE') == 'avocado-imx93-frdm' and bb.utils.contains('DISTRO_FEATURES', 'verified-boot', True, False, d):
        d.appendVar('SRC_URI', ' file://fit-verify.cfg')
        d.appendVar('DEPENDS', ' sb-keys')
        d.setVar('UBOOT_SIGN_ENABLE', '1')
        d.setVar('UBOOT_SIGN_KEYDIR', d.getVar('AVOCADO_SB_KEYS_DIR'))
        d.setVar('UBOOT_SIGN_KEYNAME', 'FIT')
}

MKENVIMAGE_EXTRA_ARGS = "-r"

# Broken, and load-bearing for nothing - kept only because the two cat lines
# below have depended on it since before this change and fixing it would move
# where avocado.cfg/env-mmc.cfg land, which is a separate change with its own
# verification. `(',', 1)[0]` is the string ',', so this is UBOOT_CONFIG.split(',')
# - a LIST, which bitbake stringifies to ['sd']. Every cat line below therefore
# writes to ${S}/configs/['sd'] and the real defconfig is never touched. Those
# fragments still reach .config, via cml1.bbclass's merge_config.sh over SRC_URI;
# the cat lines are dead. Do not add a third.
UBOOT_DEFCONFIG = "${@'${UBOOT_CONFIG}'.split((',', 1)[0])}"

do_configure:append:class-target () {
  cat ${UNPACKDIR}/avocado.cfg >> ${S}/configs/${UBOOT_DEFCONFIG}
  cat ${UNPACKDIR}/env-mmc.cfg >> ${S}/configs/${UBOOT_DEFCONFIG}
}

require recipes-bsp/u-boot/u-boot-env.inc
