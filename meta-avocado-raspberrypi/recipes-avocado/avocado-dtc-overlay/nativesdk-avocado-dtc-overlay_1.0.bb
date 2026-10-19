SUMMARY = "SDK wrapper that compiles a device-tree overlay source into a .dtbo"
DESCRIPTION = "Avocado SDK device-tree overlay build wrapper (cpp + dtc -@)"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

# The package name is a contract: avocado-cli installs exactly
# `nativesdk-avocado-dtc-overlay` into the SDK when a runtime declares
# device_tree_overlays and calls exactly `avocado-dtc-overlay`. The Qualcomm
# layer ships its own wrapper under the same name; the two never share a build
# because only one BSP's layers are present in a machine build.

SRC_URI = "file://avocado-dtc-overlay"

S = "${UNPACKDIR}"

PACKAGE_ARCH = "${SDKPKGARCH}"
PACKAGES = "${PN}"

# dtc + fdtget for the compile and the fixups assertion. The C preprocessor
# comes from the cross-canadian toolchain the SDK packagegroup already pulls
# (reached via $CPP / $CROSS_COMPILE), so it is not an RDEPENDS here.
RDEPENDS:${PN} += "nativesdk-dtc"

inherit nativesdk

do_configure[noexec] = "1"
do_compile[noexec] = "1"

do_install() {
    install -d ${D}${bindir}
    install -m 0755 ${S}/avocado-dtc-overlay ${D}${bindir}/avocado-dtc-overlay
}

FILES:${PN} += "${bindir}/avocado-dtc-overlay"
