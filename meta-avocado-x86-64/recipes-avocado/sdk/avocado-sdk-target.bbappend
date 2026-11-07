FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"
FILESEXTRAPATHS:prepend := "${@':'.join(['%s/stone' % layer for layer in d.getVar('BBLAYERS').split()])}:"

RDEPENDS:${PN}:append = " \
  nativesdk-mtools \
  nativesdk-dnsmasq \
  nativesdk-gptfdisk \
  nativesdk-util-linux-findmnt \
  nativesdk-util-linux-lsblk \
"

# The shared hook bodies. The base recipe installs only the per-machine
# avocado-{build,provision}-<machine> files, which on x86 are wrappers that
# exec these.
SRC_URI += "file://avocado-build-x86 file://avocado-provision-x86"

do_install:append() {
    install -m 0755 ${UNPACKDIR}/avocado-build-x86 ${D}${SDKPATHNATIVE}${bindir}
    install -m 0755 ${UNPACKDIR}/avocado-provision-x86 ${D}${SDKPATHNATIVE}${bindir}
}

FILES:${PN} += " \
    ${SDKPATHNATIVE}${bindir}/avocado-build-x86 \
    ${SDKPATHNATIVE}${bindir}/avocado-provision-x86 \
"
