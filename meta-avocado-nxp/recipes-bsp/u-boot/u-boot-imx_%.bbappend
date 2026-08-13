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

# AHAB is i.MX93-only here, so it rides a machine override rather than joining
# the class-target list above: the same bbappend serves avocado-imx95-frdm,
# which has none of the signing work wired up.
#
# SRC_URI is the whole wiring. oe-core's u-boot-configure.inc collects every
# .cfg in SRC_URI via find_cfgs() and merges them with merge_config.sh, so a
# fragment needs no do_configure of its own. Note that the class-target
# do_configure below is NOT what applies avocado.cfg and env-mmc.cfg -
# UBOOT_DEFCONFIG expands to the string "['sd']" rather than a defconfig name,
# so that cat has always written to a file named configs/[sd] that nothing
# reads. Those two fragments reach the build through find_cfgs like this one.
SRC_URI:append:imx93-frdm = " file://ahab.cfg"

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

# With CONFIG_AHAB_BOOT, booti stops taking a raw kernel: cmd/booti.c reads its
# first argument as an AHAB container, authenticates it, and pulls the kernel
# and fdt destinations out of it via container_get_image_dst(). Handing it the
# bare Image the stock environment loads is what produces
# "Authenticate OS container is failed" and drops the board to a prompt.
#
# So the boot flow changes shape, not just its inputs: one signed container
# replaces the separate Image and dtb loads, and the fdt argument goes away
# because the container carries that address itself. The initramfs is still
# passed as argv[1], which booti leaves alone - note it therefore stays
# unauthenticated, same as the reference BSP does it.
#
# Patched into the environment text rather than kept as a second env file so
# the non-AHAB and AHAB environments cannot drift apart in every other line.
do_compile:prepend:bootvars-ubootenv() {
    if ${@bb.utils.contains('DISTRO_FEATURES', 'ahab', 'true', 'false', d)}; then
        # The container is staged at cntr_addr, NOT at image_addr, and the two
        # must not be the same address. authenticate_os_container() memcpys each
        # image to the destination recorded inside the container - which for the
        # kernel is image_addr - and booti then calls container_get_image_dst()
        # on the container to learn where that landed. Load the container at
        # image_addr and the first step overwrites what the second reads: the ELE
        # authenticates fine, then the parse fails with "Parse kernel and fdt
        # address failed -1", or the header check reports a bad container.
        # Verified on an FRDM-IMX93 - booti at a staged address boots Linux,
        # booti at image_addr does not.
        sed -i \
            -e 's|^load_image=.*|load_image=load ${devtype} ${devnum}:${bootpart} ${cntr_addr} os_cntr_signed.bin|' \
            -e 's|^avocado_boot=.*|avocado_boot=booti ${cntr_addr} ${ramdisk_addr}:${filesize} -;|' \
            -e 's|^bootcmd=run avocado_boot_init load_image load_devicetree load_initramfs avocado_boot|bootcmd=run avocado_boot_init load_image load_initramfs avocado_boot|' \
            ${ENV_FILEPATH}

        # cntr_addr has to exist and has to differ from image_addr, per the
        # collision described above. Asserted rather than assumed because the
        # failure is a board that authenticates and then refuses to boot.
        if ! grep -q '^cntr_addr=' ${ENV_FILEPATH}; then
            bbfatal "AHAB is enabled but the environment defines no cntr_addr to stage the container at"
        fi
        if [ "$(sed -n 's/^cntr_addr=//p' ${ENV_FILEPATH})" = "$(sed -n 's/^image_addr=//p' ${ENV_FILEPATH})" ]; then
            bbfatal "cntr_addr equals image_addr; the container would be overwritten by its own payload during authentication"
        fi

        if ! grep -q 'os_cntr_signed.bin' ${ENV_FILEPATH}; then
            bbfatal "AHAB is enabled but the U-Boot environment still loads a bare kernel"
        fi
        if grep '^bootcmd=' ${ENV_FILEPATH} | grep -q 'load_devicetree'; then
            bbfatal "AHAB bootcmd still loads a separate device tree; the container carries that address itself"
        fi
    fi
}

require recipes-bsp/u-boot/u-boot-env.inc
