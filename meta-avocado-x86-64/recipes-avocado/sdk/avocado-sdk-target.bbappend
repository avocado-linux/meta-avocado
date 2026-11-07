FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"
FILESEXTRAPATHS:prepend := "${@':'.join(['%s/stone' % layer for layer in d.getVar('BBLAYERS').split()])}:"

RDEPENDS:${PN}:append = " \
  nativesdk-mtools \
  nativesdk-dnsmasq \
  nativesdk-gptfdisk \
  nativesdk-util-linux-findmnt \
  nativesdk-util-linux-lsblk \
"

# The shared build hook body. The base recipe installs only the per-machine
# avocado-build-<machine> file, which on x86 is a wrapper that execs this.
SRC_URI += "file://avocado-build-x86"

do_install:append() {
    install -m 0755 ${UNPACKDIR}/avocado-build-x86 ${D}${SDKPATHNATIVE}${bindir}
}

FILES:${PN} += "${SDKPATHNATIVE}${bindir}/avocado-build-x86"
