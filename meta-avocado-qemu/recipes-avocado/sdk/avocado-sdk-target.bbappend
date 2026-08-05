FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"
FILESEXTRAPATHS:prepend := "${@':'.join(['%s/stone' % layer for layer in d.getVar('BBLAYERS').split()])}:"

SRC_URI:append = "\
  file://vm \
"

DEPENDS:append = " nativesdk-qemu"

# The qemu-system emulator is per-arch (genuinely machine-specific).
RDEPENDS:${PN}:append:qemuarm64 = " nativesdk-qemu-system-aarch64"
RDEPENDS:${PN}:append:qemux86-64 = " nativesdk-qemu-system-x86-64"

# Disk-assembly tools are boot-method-specific: a U-Boot target assembles with
# fwup; a UEFI target uses the manifest-driven native GPT builder (sgdisk +
# mkfs.fat + mtools), mirroring the Intel target's stone-provision-img.sh. Gate
# on AVOCADO_BOOTLOADER, not the machine name.
RDEPENDS:${PN} += "${@bb.utils.contains('AVOCADO_BOOTLOADER', 'uboot', 'nativesdk-fwup nativesdk-mkfat', '', d)}"
RDEPENDS:${PN} += "${@bb.utils.contains('AVOCADO_BOOTLOADER', 'uefi', 'nativesdk-gptfdisk nativesdk-mtools nativesdk-dosfstools', '', d)}"

do_install:append() {
    install -m 0755 ${WORKDIR}/vm ${D}${SDKPATHNATIVE}${bindir}
}

# Substitute QB_MACHINE value for qemuarm64 (strip "-machine " prefix from QB_MACHINE)
QB_MACHINE_VALUE = "${@d.getVar('QB_MACHINE').replace('-machine ', '') if d.getVar('QB_MACHINE') else ''}"

do_install:append:qemuarm64() {
    sed -i 's|@QB_MACHINE@|${QB_MACHINE_VALUE}|g' ${D}${SDKPATHNATIVE}${bindir}/vm
}

FILES:${PN}:append = "\
  ${SDKPATHNATIVE}${bindir}/vm \
"
