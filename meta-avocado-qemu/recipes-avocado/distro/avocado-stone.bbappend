inherit stone

do_compile[depends] += "u-boot:do_deploy"
# The qemuarm64 manifest also consumes flash.bin (TF-A) from the deploy dir;
# without this dependency a parallel cold build can bundle before (or with a
# stale copy of) the TF-A deploy. Gated on MACHINE because avocado-qemux86-64
# shares this .bbappend and has no TF-A provider -- and because varflags take no
# override suffix on bitbake 2.8.1. Fixes #286.
do_compile[depends] += "${@bb.utils.contains('MACHINE', 'avocado-qemuarm64', 'trusted-firmware-a:do_deploy', '', d)}"

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
  install -m 0644 ${WORKDIR}/rootdisk.conf ${DEPLOYDIR}/rootdisk.conf
}

do_deploy:append:stone-direct() {
  install -d ${DEPLOYDIR}
  install -m 0755 ${WORKDIR}/stone-provision-direct.sh ${DEPLOYDIR}/stone-provision-direct.sh
}
