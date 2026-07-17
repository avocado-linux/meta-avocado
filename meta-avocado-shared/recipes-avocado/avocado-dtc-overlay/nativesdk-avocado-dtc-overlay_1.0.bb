DESCRIPTION = "Avocado SDK device-tree overlay build wrapper (cpp + dtc -@)"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

PACKAGE_ARCH = "${SDKPKGARCH}"
PACKAGES = "${PN}"

SRC_URI = " \
    file://avocado-dtc-overlay \
"

# dtc + fdtget for the compile and the fixups assertion. The C preprocessor
# comes from the cross-canadian toolchain the SDK packagegroup already pulls
# (reached via $CPP / $CROSS_COMPILE), so it is not an RDEPENDS here.
RDEPENDS:${PN} += " \
  nativesdk-dtc \
"

inherit nativesdk

do_install() {
    install -d ${D}${bindir}
    install -m 0755 ${WORKDIR}/avocado-dtc-overlay ${D}${bindir}/avocado-dtc-overlay
}

FILES:${PN} += " \
    ${bindir}/avocado-dtc-overlay \
"
