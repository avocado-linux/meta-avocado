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
SRC_URI:append:imx91-frdm = " file://ahab.cfg"

# Unrelated to AHAB, and not gated on the feature: the FRDM defconfigs enable
# capsule authentication whether or not signing is on, so a plain build breaks
# too. avocado-imx95-frdm's defconfig carries the same symbol and is likely
# broken the same way, but it is not built here and is left alone rather than
# changed unverified.
SRC_URI:append:imx93-frdm = " file://no-efi-capsule-auth.cfg"
SRC_URI:append:imx91-frdm = " file://no-efi-capsule-auth.cfg"

MKENVIMAGE_EXTRA_ARGS = "-r"

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
