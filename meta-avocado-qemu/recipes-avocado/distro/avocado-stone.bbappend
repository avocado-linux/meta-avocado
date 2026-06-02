inherit stone

do_compile[depends] += "u-boot:do_deploy"

# qemuarm64 boots via TF-A secure boot: trusted-firmware-a's do_deploy assembles
# flash.bin (bl1 + fip) into DEPLOY_DIR_IMAGE, which the stone manifest references
# as the 'bios' image. Without this edge nothing forces TF-A to compile/deploy
# before do_stone_validate reads DEPLOY_DIR_IMAGE, so on a clean build validate
# races ahead (TF-A only fetched/unpacked) and fails with "flash.bin not found".
# Machine-gated inline (varflags can't take a :append:<machine> override); x86
# has no TF-A so the dep stays empty there.
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
  install -m 0644 ${UNPACKDIR}/rootdisk.conf ${DEPLOYDIR}/rootdisk.conf
}

do_deploy:append:stone-direct() {
  install -d ${DEPLOYDIR}
  install -m 0755 ${UNPACKDIR}/stone-provision-direct.sh ${DEPLOYDIR}/stone-provision-direct.sh
}
