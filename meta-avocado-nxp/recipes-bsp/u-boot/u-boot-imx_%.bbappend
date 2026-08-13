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
# replaces the separate Image and dtb loads, and the fdt argument goes away
# because the container carries that address itself. The initramfs is still
# passed as argv[1], which booti leaves alone - note it therefore stays
# unauthenticated, same as the reference BSP does it.
#
# Patched into the environment text rather than kept as a second env file so
# the non-AHAB and AHAB environments cannot drift apart in every other line.
do_compile:prepend:bootvars-ubootenv() {
    if ${@bb.utils.contains('DISTRO_FEATURES', 'ahab', 'true', 'false', d)}; then
        sed -i \
            -e 's|^load_image=.*|load_image=load ${devtype} ${devnum}:${bootpart} ${image_addr} os_cntr_signed.bin|' \
            -e 's|^avocado_boot=.*|avocado_boot=booti ${image_addr} ${ramdisk_addr}:${filesize} -;|' \
            -e 's|^bootcmd=run avocado_boot_init load_image load_devicetree load_initramfs avocado_boot|bootcmd=run avocado_boot_init load_image load_initramfs avocado_boot|' \
            ${ENV_FILEPATH}

        if ! grep -q 'os_cntr_signed.bin' ${ENV_FILEPATH}; then
            bbfatal "AHAB is enabled but the U-Boot environment still loads a bare kernel"
        fi
        if grep '^bootcmd=' ${ENV_FILEPATH} | grep -q 'load_devicetree'; then
            bbfatal "AHAB bootcmd still loads a separate device tree; the container carries that address itself"
        fi
    fi
}

require recipes-bsp/u-boot/u-boot-env.inc
