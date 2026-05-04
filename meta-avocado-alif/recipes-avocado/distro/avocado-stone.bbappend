# In-tree deps the alif-e8-devkit provisioning scripts pull from DEPLOYDIR.
do_compile[depends] += "trusted-firmware-a:do_deploy"
do_compile[depends] += "linux-alif:do_deploy"

DEPENDS += " jq-native"

# Shared GPT-image-builder used by the sd / img profiles. The base
# avocado-stone.bb only auto-stages files for stone-img/sd/usb/peridio
# overrides; wire the custom stone-serial profile here, plus the helper
# sourced by the sd / img profile scripts.
SRC_URI += " \
    file://build-disk-image.sh \
"

SRC_URI:append:stone-serial = " \
    file://stone-provision-serial.sh \
"

do_deploy:append() {
  install -d ${DEPLOYDIR}
  install -m 0755 ${WORKDIR}/build-disk-image.sh ${DEPLOYDIR}/build-disk-image.sh
}

do_deploy:append:stone-serial() {
  install -d ${DEPLOYDIR}
  install -m 0755 ${WORKDIR}/stone-provision-serial.sh ${DEPLOYDIR}/stone-provision-serial.sh
}
