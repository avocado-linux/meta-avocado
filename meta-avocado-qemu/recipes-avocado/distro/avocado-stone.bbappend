inherit stone

do_compile[depends] += "u-boot:do_deploy"

DEPENDS += " jq-native mkfat-native fwup-native"

SRC_URI += " \
    file://rootdisk.conf \
"

# The base avocado-stone.bb only auto-stages scripts for stone-img/sd/usb
# overrides, so wire stone-direct here. The manifest always declares the
# 'direct' profile, so validation requires its script in DEPLOY_DIR_IMAGE.
SRC_URI:append:stone-direct = " \
    file://stone-provision-direct.sh \
"

do_deploy:append() {
  install -d ${DEPLOYDIR}
  install -m 0644 ${UNPACKDIR}/rootdisk.conf ${DEPLOYDIR}/rootdisk.conf
}

do_deploy:append:stone-direct() {
  install -d ${DEPLOYDIR}
  install -m 0755 ${UNPACKDIR}/stone-provision-direct.sh ${DEPLOYDIR}/stone-provision-direct.sh
}
