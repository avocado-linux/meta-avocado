# Add a nativesdk variant of android-tools that builds only fastboot.
# Used by stone-provision-emmc.sh on the rzv2n-sr-som target to drive the
# in-U-Boot fastboot endpoint over USB-OTG. adb and the rest of the suite are
# excluded to keep the SDK image small.
BBCLASSEXTEND = "native nativesdk"

TOOLS:class-nativesdk = "fastboot"

# fastboot needs libbsd, libpcre, zlib (already in DEPENDS), libcap, plus
# nativesdk variants of each. openssl is target-only in upstream; nativesdk
# fastboot doesn't need crypto.
DEPENDS:class-nativesdk = "nativesdk-libbsd nativesdk-libpcre nativesdk-zlib nativesdk-libcap"

do_install:class-nativesdk() {
    install -d ${D}${bindir}
    install -m0755 ${B}/fastboot/fastboot ${D}${bindir}/fastboot
}

# Narrow the main package to just fastboot for the nativesdk variant. Leave
# the default OE PACKAGES split intact so ${PN}-dbg picks up /usr/bin/.debug/.
FILES:${PN}:class-nativesdk = "${bindir}/fastboot"

# Drop the upstream -adbd and -fstools subpackages from the nativesdk variant.
# We don't ship adbd or the fs tools, and -adbd's RDEPENDS on android-tools-conf
# can't resolve at the nativesdk layer (android-tools-conf has no nativesdk
# BBCLASSEXTEND).
PACKAGES:remove:class-nativesdk = "${PN}-fstools ${PN}-adbd"
RDEPENDS:${PN}-adbd:class-nativesdk = ""
RDEPENDS:${PN}-fstools:class-nativesdk = ""
SYSTEMD_PACKAGES:class-nativesdk = ""
