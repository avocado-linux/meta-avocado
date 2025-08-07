FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"
FILESEXTRAPATHS:prepend := "${@':'.join(['%s/stone' % layer for layer in d.getVar('BBLAYERS').split()])}:"

SRC_URI:append = "\
  file://avocado-run-qemu \
  file://${MACHINE_SHORT_NAME}/rootdisk.conf \
  file://${MACHINE_SHORT_NAME}/stone-provision.sh \
"

SHARED_RDEPENDS = "\
  nativesdk-fwup \
  nativesdk-mkfat \
  nativesdk-jq \
"

DEPENDS:append = " nativesdk-qemu"
RDEPENDS:${PN}:append:qemuarm64 = " \
  nativesdk-qemu-system-aarch64 \
  ${SHARED_RDEPENDS} \
"
RDEPENDS:${PN}:append:qemux86-64 = " \
  nativesdk-qemu-system-x86-64 \
  ${SHARED_RDEPENDS} \
"

do_install:append() {
    install -m 0755 ${WORKDIR}/avocado-run-qemu ${D}${SDKPATHNATIVE}${bindir}
    install -d ${D}${SDKPATHNATIVE}/stone/${MACHINE_SHORT_NAME}
    install -m 0644 ${WORKDIR}/${MACHINE_SHORT_NAME}/rootdisk.conf ${D}${SDKPATHNATIVE}/stone/${MACHINE_SHORT_NAME}/rootdisk.conf
    install -m 0755 ${WORKDIR}/${MACHINE_SHORT_NAME}/stone-provision.sh ${D}${SDKPATHNATIVE}/stone/${MACHINE_SHORT_NAME}/stone-provision.sh
}

FILES:${PN}:append = "\
  ${SDKPATHNATIVE}${bindir}/avocado-run-qemu \
"
