inherit stone

DEPENDS += " jq-native"

# --- U-Boot targets (AVOCADO_BOOTLOADER=uboot): fwup assembly + TF-A ---------
# A U-Boot target's stone manifest references flash.bin (TF-A bl1 + fip) as its
# 'bios' image and assembles the disk with fwup from rootdisk.conf. Force U-Boot
# and TF-A to deploy before do_stone_validate reads DEPLOY_DIR_IMAGE, otherwise a
# clean build races ahead (artifacts only fetched/unpacked) and validate fails
# with "flash.bin not found". Gated on AVOCADO_BOOTLOADER, a machine property, so
# any U-Boot target inherits it (default uboot; x86 sets uefi).
do_compile[depends] += "${@bb.utils.contains('AVOCADO_BOOTLOADER', 'uboot', 'u-boot:do_deploy trusted-firmware-a:do_deploy', '', d)}"
DEPENDS += "${@bb.utils.contains('AVOCADO_BOOTLOADER', 'uboot', 'mkfat-native fwup-native', '', d)}"

SRC_URI += "${@bb.utils.contains('AVOCADO_BOOTLOADER', 'uboot', 'file://rootdisk.conf', '', d)}"
do_deploy:append() {
  if [ "${AVOCADO_BOOTLOADER}" = "uboot" ]; then
    install -d ${DEPLOYDIR}
    install -m 0644 ${WORKDIR}/rootdisk.conf ${DEPLOYDIR}/rootdisk.conf
  fi
}

# --- UEFI targets (AVOCADO_BOOTLOADER=uefi): systemd-boot, native GPT builder -
# Mirrors the avocado-x86-64 (Intel) target: the ESP carries systemd-boot plus
# its loader config, so both must be deployed before stone bundles the boot
# partition. (ovmf is the QEMU UEFI firmware; real UEFI hardware pulls its own.)
do_compile[depends] += "${@bb.utils.contains('AVOCADO_BOOTLOADER', 'uefi', 'systemd-boot:do_deploy systemd-bootconf:do_deploy ovmf:do_deploy', '', d)}"

# --- both qemu machines declare the 'direct' profile ------------------------
# The base avocado-stone.bb only auto-stages scripts for stone-img/sd/usb
# overrides, so wire stone-direct here.
SRC_URI:append:stone-direct = " file://stone-provision-direct.sh"
do_deploy:append:stone-direct() {
  install -d ${DEPLOYDIR}
  install -m 0755 ${WORKDIR}/stone-provision-direct.sh ${DEPLOYDIR}/stone-provision-direct.sh
}
