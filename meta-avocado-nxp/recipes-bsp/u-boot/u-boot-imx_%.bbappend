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
# AHAB (i.MX9) signed-boot support in U-Boot, gated on the 'ahab'
# DISTRO_FEATURE: machine-only gating compiled CONFIG_AHAB_BOOT=y into every
# imx93-frdm/imx91-frdm u-boot, so booti demanded a signed container even on
# builds that never constructed one ("Authenticate OS container is failed" on a
# plain build). The EFI capsule options the stock defconfig enables are already
# turned off for every board and version by disable-unused-vendor-features.cfg.
SRC_URI:append:imx93-frdm = "${@bb.utils.contains('DISTRO_FEATURES', 'ahab', ' file://ahab.cfg', '', d)}"
SRC_URI:append:imx91-frdm = "${@bb.utils.contains('DISTRO_FEATURES', 'ahab', ' file://ahab.cfg', '', d)}"

# disable-unused-vendor-features.cfg turns off NXP stock defconfig defaults
# (EFI capsule-on-disk, USB DFU) that Avocado never uses and that do not build
# in this layer set - see the fragment's own header. Every u-boot-imx board:
# the same symbols are on in the imx8mp-evk, imx91/93/95-frdm defconfigs alike.
SRC_URI:append:class-target = " file://disable-unused-vendor-features.cfg"

# fit.cfg enables base FIT container support (CONFIG_FIT) on every u-boot-imx
# board. Capability, not policy: it is already =y in the stock imx8m/imx9
# defconfigs and costs nothing where the env still boots loose files, and a
# machine that flips to `bootm fitImage` (avocado-imx-fit.inc) must be able to
# parse a FIT whether or not signing is on.
# fit.cfg enables base FIT container support (CONFIG_FIT) unconditionally on
# avocado-imx93-frdm. The boot partition manifest (stone-imx93-frdm.json) and
# the U-Boot env boot command (avocado-imx93-frdm.env) are both static
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
# the real defconfig is never touched. Confirmed from temp/run.do_configure and
# log.do_configure on a real build. A fragment added only via a cat line
# therefore reaches nothing, silently - which for a verification Kconfig means
# shipping a bootloader that enforces nothing.
SRC_URI:append:class-target = " file://fit.cfg"

# fit-verify.cfg enables U-Boot FIT signature verification, and the same gate
# embeds the FIT public key into U-Boot's own control DTB so the running
# bootloader carries its own trust anchor rather than reading the key from
# writable storage (spec: "the verification key is not modifiable from the
# running system"). Gated on the 'verified-boot' DISTRO_FEATURES token alone -
# no machine check - so every u-boot-imx board that opts in gets the same
# treatment; a board whose env still boots loose files with booti is unaffected
# by CONFIG_FIT_SIGNATURE (it only ever acts inside bootm).
# Compile the Avocado boot flow into U-Boot's default environment.
#
# Until this landed, the flow (bootcmd, avocado_boot_init, load_image,
# avocado_boot and the variables they read) reached U-Boot ONLY as the saved
# environment: u-boot-env.inc runs mkenvimage over env/${MACHINE}.txt and fwup
# writes the result to the uboot-env partition. That is exactly what
# CONFIG_ENV_WRITEABLE_LIST rejects - env/mmc.c imports the saved copy with
# H_EXTERNAL and env/flags.c drops every H_EXTERNAL variable missing the 'w'
# access flag - so the permit list alone would leave the board running U-Boot's
# stock bootcmd with no Avocado boot path at all.
#
# Unconditional for this machine rather than gated on verified-boot, for the
# same reason fit.cfg is unconditional: a build without the feature has to boot
# the same way as one with it. Without the feature the saved environment is
# still imported and still wins, so nothing changes for those builds.
#
# env/${MACHINE}.txt deliberately keeps its own full copy of the flow, and must.
# env/env.c's env_load() seeds the built-in default before the storage driver
# only under CONFIG_ENV_WRITEABLE_LIST; with the feature off the hash table is
# built from the saved environment alone, so a reduced .txt would leave those
# builds with no bootcmd. See the debt marker there.
#
# avocado-imx93-frdm.env includes the vendor's own board .env, which is what
# the build picked up before this and which supplies values the flow relies on
# without setting them - initrd_high, and the fastboot/manufacturing helpers
# that uuu recovery uses.
SRC_URI:append:avocado-imx93-frdm = " file://env-compiled-in.cfg file://avocado-imx93-frdm.env"

# CONFIG_ENV_SOURCE_FILE resolves against board/$(SYS_VENDOR)/$(SYS_BOARD),
# which board/nxp/imx93_frdm/Kconfig fixes at nxp/imx93_frdm for this target.
# No bitbake variable carries it, so the path is spelled out.
#
# It is spelled out TWICE - here, and in the fragment's own #include - and both
# assume the 2026.04 layout. This is a `%` bbappend and the machine no longer
# pins a version, so u-boot-imx 2025.04 is still reachable, and 2025.04 keeps
# this board at board/freescale/imx93_frdm instead. Guard rather than let
# `install` fail: its "cannot create regular file" names a path that appears in
# no recipe, and CONFIG_ENV_SOURCE_FILE exists in 2025.04 too, so merge_config
# accepts the fragment silently and offers no second chance to notice.
do_configure:prepend:avocado-imx93-frdm () {
    if [ ! -d ${S}/board/nxp/imx93_frdm ]; then
        bbfatal "board/nxp/imx93_frdm is absent from ${S}. u-boot-imx 2025.04 keeps this board at board/freescale/imx93_frdm; the compiled-in environment (CONFIG_ENV_SOURCE_FILE, and the #include inside avocado-imx93-frdm.env) assumes the 2026.04 layout. Build this machine against 2026.04, or teach both paths about the older layout."
    fi
    install -m 0644 ${UNPACKDIR}/avocado-imx93-frdm.env \
        ${S}/board/nxp/imx93_frdm/avocado.env
}

# fit-verify.cfg enables U-Boot FIT signature verification. It is NOT
# unconditional like fit.cfg above: it is only meaningful on
# avocado-imx93-frdm (the only machine this change wires a FIT signing key
# for) and only when the customer has opted in via the 'verified-boot'
# DISTRO_FEATURES token, so every other NXP board and every frdm build
# without the feature build exactly as before (still gets an unsigned FIT
# via fit.cfg above, but no signature enforcement).
#
# u-boot.inc already unconditionally inherits OE-core's uboot-sign.bbclass, so
# setting UBOOT_SIGN_ENABLE plus the same UBOOT_SIGN_KEYDIR/UBOOT_SIGN_KEYNAME
# ="FIT" pair avocado-imx-fit.inc sets for the kernel-fit-image side is enough:
# uboot-sign's do_uboot_assemble_fitimage task (added unconditionally by
# u-boot.inc, gated internally on UBOOT_SIGN_ENABLE) runs mkimage -f auto-conf
# against AVOCADO_SB_KEYS_DIR/FIT.crt and embeds the PUBLIC half only into
# u-boot.dtb before it is concatenated into the final u-boot binary - the
# private FIT.key never leaves the build host. The imx8m/imx9 defconfigs build
# with CONFIG_OF_SEPARATE=y, the precondition uboot-sign.bbclass documents for
# this embedding step, so no CONFIG_DEFAULT_DEVICE_TREE/binman fallback is
# needed. DEPENDS on sb-keys is added under the same gate so FIT.crt exists in
# AVOCADO_SB_KEYS_DIR before this recipe's fitimage-assemble task runs.
python () {
    if bb.utils.contains('DISTRO_FEATURES', 'verified-boot', True, False, d):
        d.appendVar('SRC_URI', ' file://fit-verify.cfg')
        # Saved-environment lockdown, for the boards that carry a permit list
        # and a compiled-in boot flow (env-compiled-in.cfg): the list is
        # CFG_ENV_FLAGS_LIST_STATIC, a C #define in that board's config header
        # that env-writeable-list.patch adds, so it cannot be a .cfg entry, and
        # env-writeable-list.cfg's CONFIG_ENV_WRITEABLE_LIST without it would
        # reject every saved variable - avocado_boot_slot included. The two
        # ride the same gate and the same machine scope on purpose; a board
        # whose Avocado boot flow still lives only in the saved environment
        # must not get either.
        if d.getVar('MACHINE') == 'avocado-imx93-frdm':
            d.appendVar('SRC_URI', ' file://env-writeable-list.cfg file://env-writeable-list.patch')
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
# replaces the separate Image, dtb and initramfs loads, and both trailing
# arguments go away. The fdt address comes out of the container, and the
# initramfs is bundled into the kernel Image (INITRAMFS_IMAGE_BUNDLE, set in
# the machine configuration) so it rides inside the signed exec payload.
#
# booti never authenticates argv[1], so leaving the initramfs there would leave
# the component that unlocks LUKS /var outside the chain. Passing "-" instead
# is the documented no-ramdisk form - boot/image-board.c:474 compares the
# selector against "-" before trying to locate one.
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
            -e 's|^avocado_boot=.*|avocado_boot=booti ${cntr_addr} - -;|' \
            -e 's|^bootcmd=run avocado_boot_init load_image load_devicetree load_initramfs avocado_boot|bootcmd=run avocado_boot_init load_image avocado_boot|' \
            -e 's|^fdt_addr=.*|fdt_addr=0x94000000|' \
            -e 's|^bootm_size=.*|bootm_size=0x40000000|' \
            ${ENV_FILEPATH}

        # fdt_addr and bootm_size are rewritten here rather than carried in the
        # environment, because only the signed path needs them. The bundled
        # kernel is ~200 MB and unpacks over the stock fdt_addr, and reaching
        # the new one needs a window wider than NXP's 256 MiB. An unsigned build
        # loads a ~33 MB kernel and is fine with the stock values, so moving
        # them unconditionally would change a boot path this feature does not
        # own.
        #
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

        # The whole point of ENG-2418. A separate initramfs load reintroduces an
        # unauthenticated argv[1], and it fails open rather than loudly: the
        # board boots, /var unlocks, and nothing reports that the initrd that
        # derived the key was never checked.
        if grep '^bootcmd=' ${ENV_FILEPATH} | grep -q 'load_initramfs'; then
            bbfatal "AHAB bootcmd still loads a separate initramfs; booti never authenticates it, so it must be bundled into the kernel Image instead"
        fi
        if grep -q '^avocado_boot=.*ramdisk_addr' ${ENV_FILEPATH}; then
            bbfatal "AHAB boot command still passes a ramdisk argument to booti; that argument is never authenticated"
        fi
    fi
}

require recipes-bsp/u-boot/u-boot-env.inc
