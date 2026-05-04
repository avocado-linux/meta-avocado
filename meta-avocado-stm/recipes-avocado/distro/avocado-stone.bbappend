# Stone bundle deps: TF-A FSBL, FIP (combines TF-A BL31 + OP-TEE + U-Boot),
# the kernel Image + DTB, and the boot-partition extlinux.conf must all be
# in DEPLOY_DIR_IMAGE before stone runs. We don't ride the upstream BSP's
# core-image WIC pipeline (which would have wired EXTRA_IMAGEDEPENDS for
# us), so name the producers explicitly.
do_compile[depends] += "tf-a-stm32mp:do_deploy"
do_compile[depends] += "fip-stm32mp:do_deploy"
do_compile[depends] += "optee-os-stm32mp:do_deploy"
do_compile[depends] += "u-boot-stm32mp:do_deploy"
do_compile[depends] += "virtual/kernel:do_deploy"
do_compile[depends] += "extlinux-stm32mp25-dk:do_deploy"

DEPENDS += " jq-native"

# Shared GPT-image-build helper used by sd / emmc / serial profiles. The base
# avocado-stone.bb only auto-stages files for the stone-img/sd/usb
# overrides; wire stone-emmc and stone-serial here, plus the helper that all
# three profile scripts source.
SRC_URI += " \
    file://build-disk-image.sh \
"

SRC_URI:append:stone-emmc = " \
    file://stone-provision-emmc.sh \
"

SRC_URI:append:stone-serial = " \
    file://stone-provision-serial.sh \
"

do_deploy:append() {
  install -d ${DEPLOYDIR}
  install -m 0755 ${WORKDIR}/build-disk-image.sh ${DEPLOYDIR}/build-disk-image.sh
}

do_deploy:append:stone-emmc() {
  install -d ${DEPLOYDIR}
  install -m 0755 ${WORKDIR}/stone-provision-emmc.sh ${DEPLOYDIR}/stone-provision-emmc.sh
}

do_deploy:append:stone-serial() {
  install -d ${DEPLOYDIR}
  install -m 0755 ${WORKDIR}/stone-provision-serial.sh ${DEPLOYDIR}/stone-provision-serial.sh
}
