inherit stone

# Which bootloader artifacts stone needs is a property of how the target boots,
# so gate them on AVOCADO_BOOTLOADER rather than the machine name (varflags take
# no :append:<override>). qemux86-64 moves to UEFI/systemd-boot with the
# encrypted-/var work: it declares no virtual/bootloader and its rootdisk.conf is
# gone, because stone lays its GPT out natively instead of assembling one with
# fwup. Left ungated, this file would fail that machine three ways - an
# unresolvable u-boot dependency, a fetch for a file that no longer exists, and a
# do_deploy install of it.
do_compile[depends] += "${@bb.utils.contains('AVOCADO_BOOTLOADER', 'uboot', 'u-boot:do_deploy', '', d)}"

# A UEFI target's ESP carries systemd-boot plus its loader config, so both have to
# deploy before stone bundles the boot partition - the same pair the avocado-x86-64
# (Intel) sibling already depends on. ovmf is not a stone artifact and the manifest
# never names it; it is here because nothing else in this layer pulls OVMF into the
# build, and without it the ovmf_%.bbappend that turns on TPM2_ENABLE never runs, so
# the firmware measures nothing and the PCR-7 seal has no chain to bind to.
do_compile[depends] += "${@bb.utils.contains('AVOCADO_BOOTLOADER', 'uefi', 'systemd-boot:do_deploy systemd-bootconf:do_deploy ovmf:do_deploy', '', d)}"

# qemuarm64 boots via TF-A secure boot: trusted-firmware-a's do_deploy assembles
# flash.bin (bl1 + fip) into DEPLOY_DIR_IMAGE, which the stone manifest references
# as the 'bios' image. Without this edge nothing forces TF-A to compile/deploy
# before do_stone_validate reads DEPLOY_DIR_IMAGE, so on a clean build validate
# races ahead (TF-A only fetched/unpacked) and fails with "flash.bin not found".
# Machine-gated inline (varflags can't take a :append:<machine> override); x86
# has no TF-A so the dep stays empty there.
do_compile[depends] += "${@bb.utils.contains('MACHINE', 'avocado-qemuarm64', 'trusted-firmware-a:do_deploy', '', d)}"

DEPENDS += " jq-native"
DEPENDS += "${@bb.utils.contains('AVOCADO_BOOTLOADER', 'uboot', ' mkfat-native fwup-native', '', d)}"

SRC_URI += "${@bb.utils.contains('AVOCADO_BOOTLOADER', 'uboot', 'file://rootdisk.conf', '', d)}"

# The base avocado-stone.bb only auto-stages scripts for stone-img/sd/usb
# overrides, so wire stone-direct here. The manifest always declares the
# 'direct' profile, so validation requires its script in DEPLOY_DIR_IMAGE.
SRC_URI:append:stone-direct = " \
    file://stone-provision-direct.sh \
"

do_deploy:append() {
  if [ "${AVOCADO_BOOTLOADER}" = "uboot" ]; then
    install -d ${DEPLOYDIR}
    install -m 0644 ${UNPACKDIR}/rootdisk.conf ${DEPLOYDIR}/rootdisk.conf
  fi
}

do_deploy:append:stone-direct() {
  install -d ${DEPLOYDIR}
  install -m 0755 ${UNPACKDIR}/stone-provision-direct.sh ${DEPLOYDIR}/stone-provision-direct.sh
}
