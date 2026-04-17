do_compile[depends] += "u-boot:do_deploy"
do_compile[depends] += "rpi-bootfiles:do_deploy"
do_compile[depends] += "${@'rpi-tryboot-files:do_deploy' if d.getVar('RPI_USE_U_BOOT') == '0' else ''}"

DEPENDS += " jq-native mkfat-native fwup-native"

SRC_URI:append = " \
    file://rootdisk.conf \
    file://stone-tryboot-common.sh \
    file://stone-rpiboot-common.sh \
"

SRC_URI:append:stone-usb-emmc = " \
    file://stone-provision-usb-emmc.sh \
"

SRC_URI:append:stone-usb-nvme = " \
    file://stone-provision-usb-nvme.sh \
"

SRC_URI:append:stone-usb-sata = " \
    file://stone-provision-usb-sata.sh \
"

SRC_URI:append:stone-usb-sd = " \
    file://stone-provision-usb-sd.sh \
"

do_deploy:append() {
  install -d ${DEPLOYDIR}
  install -m 0644 ${WORKDIR}/rootdisk.conf ${DEPLOYDIR}/rootdisk.conf
  install -m 0755 ${WORKDIR}/stone-tryboot-common.sh ${DEPLOYDIR}/stone-tryboot-common.sh
  install -m 0755 ${WORKDIR}/stone-rpiboot-common.sh ${DEPLOYDIR}/stone-rpiboot-common.sh
}

do_deploy:append:stone-usb-emmc() {
  install -m 0755 ${WORKDIR}/stone-provision-usb-emmc.sh ${DEPLOYDIR}/stone-provision-usb-emmc.sh
}

do_deploy:append:stone-usb-nvme() {
  install -m 0755 ${WORKDIR}/stone-provision-usb-nvme.sh ${DEPLOYDIR}/stone-provision-usb-nvme.sh
}

do_deploy:append:stone-usb-sata() {
  install -m 0755 ${WORKDIR}/stone-provision-usb-sata.sh ${DEPLOYDIR}/stone-provision-usb-sata.sh
}

do_deploy:append:stone-usb-sd() {
  install -m 0755 ${WORKDIR}/stone-provision-usb-sd.sh ${DEPLOYDIR}/stone-provision-usb-sd.sh
}
