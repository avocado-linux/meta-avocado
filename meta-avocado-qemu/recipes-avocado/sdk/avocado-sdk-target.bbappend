FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"
FILESEXTRAPATHS:prepend := "${@':'.join(['%s/stone' % layer for layer in d.getVar('BBLAYERS').split()])}:"

SRC_URI:append = "\
  file://avocado-run-qemu \
  file://${MACHINE_SHORT_NAME}/rootdisk.conf \
"
DEPENDS:append = " nativesdk-qemu"
RDEPENDS:${PN}:append:qemuarm64 = " nativesdk-qemu-system-aarch64 nativesdk-fwup"
RDEPENDS:${PN}:append:qemux86-64 = " nativesdk-qemu-system-x86-64 nativesdk-fwup"

do_install:append() {
    install -m 0755 ${WORKDIR}/avocado-run-qemu ${D}${SDKPATHNATIVE}${bindir}
    install -d ${D}${SDKPATHNATIVE}/stone/${MACHINE_SHORT_NAME}
    install -m 0644 ${WORKDIR}/${MACHINE_SHORT_NAME}/rootdisk.conf ${D}${SDKPATHNATIVE}/stone/${MACHINE_SHORT_NAME}/rootdisk.conf
}

FILES:${PN}:append = "\
  ${SDKPATHNATIVE}${bindir}/avocado-run-qemu \
"
