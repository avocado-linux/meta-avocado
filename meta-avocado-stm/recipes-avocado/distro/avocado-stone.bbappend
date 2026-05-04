# Stone bundle deps: TF-A FIP, OP-TEE, U-Boot artifacts, and the boot-partition
# extlinux.conf must all be in DEPLOYDIR before stone runs.
do_compile[depends] += "tf-a-stm32mp:do_deploy"
do_compile[depends] += "optee-os-stm32mp:do_deploy"
do_compile[depends] += "u-boot-stm32mp:do_deploy"
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
