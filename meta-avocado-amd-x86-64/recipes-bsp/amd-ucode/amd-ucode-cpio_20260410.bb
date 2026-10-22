SUMMARY = "AMD CPU microcode packed as an early-load initrd"
DESCRIPTION = "Deploys amd-ucode.cpio, an uncompressed cpio carrying \
kernel/x86/microcode/AuthenticAMD.bin. The kernel applies microcode only \
from an uncompressed cpio at the very start of the initrd, before it \
unpacks the initramfs proper, so a copy under /usr/lib/firmware is never \
used. The boot entry loads this file as the first initrd."
LICENSE = "Firmware-amd-ucode"
NO_GENERIC_LICENSE[Firmware-amd-ucode] = "LICENSE.amd-ucode"
LIC_FILES_CHKSUM = "file://LICENSE.amd-ucode;md5=450f217aadc787514165e9568652d700"

# linux-firmware lists /usr/lib/firmware in SYSROOT_DIRS_IGNORE, so no other
# recipe can take the blobs from its sysroot. Fetch the same release tarball
# instead - same URL and checksum as oe-core's linux-firmware, so DL_DIR
# already holds it - and pull out only the amd-ucode members.
# devtool-debt: PV and sha256sum duplicate oe-core's linux-firmware pin.
# Ceiling: the early microcode trails the rootfs firmware after an oe-core
# linux-firmware bump. Upgrade trigger: oe-core moves linux-firmware off
# 20260410, or starts staging amd-ucode into the sysroot.
SRC_URI = "${KERNELORG_MIRROR}/linux/kernel/firmware/linux-firmware-${PV}.tar.xz;unpack=0"
SRC_URI[sha256sum] = "b7812ed6d59f6b09ecceddaa0be842a7e82a79cc0e46ca60478a4ebf02f1e178"

# do_unpack checks S before its postfuncs run, so the members are extracted
# with the tarball's top directory stripped, straight into UNPACKDIR.
S = "${UNPACKDIR}"
B = "${WORKDIR}/build"

INHIBIT_DEFAULT_DEPS = "1"
DEPENDS = "cpio-native"

PACKAGE_ARCH = "${MACHINE_ARCH}"
COMPATIBLE_MACHINE = "avocado-amd-x86-64"

inherit deploy nopackages

# Runs inside do_unpack so LICENSE.amd-ucode exists before do_populate_lic
# checks it; the rest of the ~500 MB tarball is never written out.
extract_amd_ucode() {
    tar -xJf ${DL_DIR}/linux-firmware-${PV}.tar.xz -C ${UNPACKDIR} \
        --strip-components=1 --wildcards \
        'linux-firmware-${PV}/amd-ucode/microcode_amd*.bin' \
        'linux-firmware-${PV}/LICENSE.amd-ucode'
}
do_unpack[postfuncs] += "extract_amd_ucode"
do_unpack[depends] += "xz-native:do_populate_sysroot"

do_compile() {
    rm -rf ${B}/early ${B}/amd-ucode.cpio
    install -d ${B}/early/kernel/x86/microcode
    # One container per CPU family; the loader walks the concatenation and
    # picks the patch matching this CPU's signature.
    cat ${S}/amd-ucode/microcode_amd*.bin > ${B}/early/kernel/x86/microcode/AuthenticAMD.bin
    find ${B}/early -exec touch -h -d @${SOURCE_DATE_EPOCH} {} +
    (cd ${B}/early && find . | LC_ALL=C sort | cpio --quiet -o -H newc -R 0:0 --reproducible > ${B}/amd-ucode.cpio)
}

do_install[noexec] = "1"

do_deploy() {
    install -m 0644 ${B}/amd-ucode.cpio ${DEPLOYDIR}/amd-ucode.cpio
}
addtask deploy after do_compile before do_build
