# Depend on whichever bootloader the machine selects (u-boot-imx for the NXP
# EVK/FRDM, u-boot-compulab for CompuLab, u-boot-variscite for Variscite), not
# a hardcoded recipe. virtual/bootloader rather than ${IMX_DEFAULT_BOOTLOADER}:
# Variscite selects its bootloader through PREFERRED_PROVIDER_virtual/bootloader
# alone and leaves IMX_DEFAULT_BOOTLOADER at imx-base.inc's u-boot-imx, which is
# not COMPATIBLE_MACHINE for its boards, so the old form had no provider there.
do_compile[depends] += "virtual/bootloader:do_deploy"
do_compile[depends] += "imx-boot:do_deploy"

# avocado-imx-fitimage assembles the FIT a FIT-booting machine's boot partition
# manifest expects (any machine requiring avocado-imx-fit.inc); virtual/kernel's own do_deploy (implied above via
# IMX_DEFAULT_BOOTLOADER/imx-boot) only deploys the discrete Image/dtb files
# linux-imx itself produces, not the FIT bundling them - that is a separate
# recipe now (kernel.bbclass rejects KERNEL_IMAGETYPE=fitImage in this oe-core
# release; see avocado-imx-fitimage.bb's own header).
do_compile[depends] += "${@bb.utils.contains('KERNEL_CLASSES', 'kernel-fit-extra-artifacts', ' avocado-imx-fitimage:do_deploy', '', d)}"

DEPENDS += " jq-native mkfat-native fwup-native"

# fw_setenv, for stone-provision-uuu-emmc.sh, which patches devnum and mmcblk
# into the U-Boot environment inside the disk image before writing it. jq and
# fwup arrive above; fw_setenv had no provider, so do_stone_provision died with
# "fw_setenv: command not found" the first time that profile was selected.
# libubootenv ships it (it also PROVIDES u-boot-fw-utils).
#
# Scoped to the profile that calls it rather than added to the shared
# avocado-stone.bb: 5 of the 30 avocado-*.conf machines list uuu-emmc in
# STONE_PROVISIONING, and the other 25 would build a native package for a
# script they never deploy.
DEPENDS:append:stone-uuu-emmc = " libubootenv-native"

SRC_URI += " \
    file://rootdisk.conf \
"

SRC_URI:append:stone-uuu-emmc = " \
    file://stone-provision-uuu-emmc.sh \
"

do_deploy:append() {
  install -d ${DEPLOYDIR}
  install -m 0644 ${UNPACKDIR}/rootdisk.conf ${DEPLOYDIR}/rootdisk.conf
  # The manifests name a rootfs dm-verity hash image (rootfs_hash) for the
  # per-slot hash partitions. A project build produces the real tree when
  # rootfs.image.verity is on; the distro's own bundle never does - its FIT
  # carries no root hash, so the partition content is never read - but stone
  # validate/bundle still require the file. Same zero-filled placeholder the
  # runtime build writes when verity is off.
  truncate -s 4096 ${DEPLOYDIR}/avocado-image-rootfs-${MACHINE_SHORT_NAME}.verity
}

do_deploy:append:stone-uuu-emmc() {
  install -d ${DEPLOYDIR}
  install -m 0755 ${UNPACKDIR}/stone-provision-uuu-emmc.sh ${DEPLOYDIR}/stone-provision-uuu-emmc.sh
}
