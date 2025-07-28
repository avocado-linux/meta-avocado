FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

SRC_URI:append = "\
  file://avocado-run-qemu \
"
DEPENDS:append = " nativesdk-qemu"
RDEPENDS:${PN}:append:qemuarm64 = " nativesdk-qemu-system-aarch64"
RDEPENDS:${PN}:append:qemux86-64 = " nativesdk-qemu-system-x86-64"

do_install:append() {
    install -m 0755 ${WORKDIR}/avocado-run-qemu ${D}${SDKPATHNATIVE}${bindir}
}

FILES:${PN}:append = "\
  ${SDKPATHNATIVE}${bindir}/avocado-run-qemu \
"
