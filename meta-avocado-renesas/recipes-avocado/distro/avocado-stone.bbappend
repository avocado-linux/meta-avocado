# Stone bundle deps: BL2/FIP, the on-target Flash_Writer.mot, U-Boot artifacts,
# and the boot-partition extlinux.conf must all be in DEPLOYDIR before stone runs.
do_compile[depends] += "firmware-pack:do_deploy"
do_compile[depends] += "flash-writer:do_deploy"
do_compile[depends] += "u-boot:do_deploy"
do_compile[depends] += "extlinux-rzv2n-sr-som:do_deploy"

DEPENDS += " jq-native"

# Shared GPT-image-build helper used by both the sd and emmc profiles. The
# base avocado-stone.bb only auto-stages files for stone-img/sd/usb/peridio
# overrides, so we wire stone-serial and stone-emmc here, plus the helper
# that both profile scripts source.
SRC_URI += " \
    file://build-disk-image.sh \
"

SRC_URI:append:stone-serial = " \
    file://stone-provision-serial.sh \
"

SRC_URI:append:stone-emmc = " \
    file://stone-provision-emmc.sh \
"

do_deploy:append() {
  install -d ${DEPLOYDIR}
  install -m 0755 ${WORKDIR}/build-disk-image.sh ${DEPLOYDIR}/build-disk-image.sh
}

do_deploy:append:stone-serial() {
  install -d ${DEPLOYDIR}
  install -m 0755 ${WORKDIR}/stone-provision-serial.sh ${DEPLOYDIR}/stone-provision-serial.sh
}

do_deploy:append:stone-emmc() {
  install -d ${DEPLOYDIR}
  install -m 0755 ${WORKDIR}/stone-provision-emmc.sh ${DEPLOYDIR}/stone-provision-emmc.sh
}
