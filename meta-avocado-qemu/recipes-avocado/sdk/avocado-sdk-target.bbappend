FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"
FILESEXTRAPATHS:prepend := "${@':'.join(['%s/stone' % layer for layer in d.getVar('BBLAYERS').split()])}:"

SRC_URI:append = "\
  file://vm \
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
    install -m 0755 ${WORKDIR}/vm ${D}${SDKPATHNATIVE}${bindir}
}

FILES:${PN}:append = "\
  ${SDKPATHNATIVE}${bindir}/vm \
"
