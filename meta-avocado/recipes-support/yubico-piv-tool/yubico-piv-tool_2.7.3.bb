DESCRIPTION = "Yubico PIV tool and library for managing PIV credentials on YubiKeys"
HOMEPAGE = "https://developers.yubico.com/yubico-piv-tool/"
LICENSE = "BSD-2-Clause"
LIC_FILES_CHKSUM = "file://COPYING;md5=b83cd346ac9e78624518062f20fdeebe"

SRC_URI = "git://github.com/Yubico/yubico-piv-tool.git;protocol=https;branch=master"
SRCREV = "ed1cd7862d39a92502c0476f53dfcf93f195007a"

S = "${WORKDIR}/git"

inherit cmake pkgconfig

# libcheck: lib/CMakeLists.txt does an unconditional add_subdirectory(tests),
# and lib/tests uses find_check() -> pkg_check_modules(LIBCHECK REQUIRED check).
# There is no upstream option to skip it (still unconditional on master), so the
# dependency is real rather than optional.
DEPENDS = "pcsc-lite openssl gengetopt-native libcheck"

EXTRA_OECMAKE = " \
    -DBACKEND=pcsc \
    -DGENERATE_MAN_PAGES=OFF \
    -DENABLE_HARDWARE_TESTS=OFF \
    -DENABLE_COVERAGE=OFF \
"

PACKAGES =+ "libykpiv ykcs11"

FILES:libykpiv = "${libdir}/libykpiv${SOLIBS}"
FILES:${PN}-dev += "${libdir}/libykpiv.so ${libdir}/pkgconfig/ykpiv.pc ${includedir}/ykpiv/"
FILES:ykcs11 = "${libdir}/libykcs11${SOLIBS} ${libdir}/pkgconfig/ykcs11.pc"
FILES:${PN} = "${bindir}/yubico-piv-tool"

RDEPENDS:libykpiv = "pcsc-lite-lib"
RDEPENDS:ykcs11 = "libykpiv"
