SUMMARY = "C++ library for geodesic, map projection and geoid calculations"
DESCRIPTION = "GeographicLib is a small set of C++ classes for performing conversions \
between geographic, UTM, UPS, MGRS, geocentric, and local cartesian coordinates, for \
gravity, geoid height, and geomagnetic field calculations, and for solving geodesic problems."
HOMEPAGE = "https://geographiclib.sourceforge.io"
SECTION = "libs"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://LICENSE.txt;md5=355ddc9bb1806d2d03ff21dd176ad2aa"

# The release tarball, not the git tag: only the tarball carries the VERSION
# file, without which CMake treats the tree as a development checkout, turns
# warnings into errors and requires pod2man to build the man pages.
SRC_URI = "${SOURCEFORGE_MIRROR}/${BPN}/distrib-C++/GeographicLib-${PV}.tar.gz"
SRC_URI[sha256sum] = "f35158cfb8bbc18ddc4930ee4db754b0a50d8d8d8b6700a5cad0dc987546764d"

S = "${UNPACKDIR}/GeographicLib-${PV}"

inherit cmake

# Static as well as shared keeps parity with the 1.x recipe in meta-ros-common
# that this one supersedes, so consumers linking the static archive still find it.
# The data path is baked into the library as the default lookup location.
EXTRA_OECMAKE += "-DBUILD_BOTH_LIBS=ON -DGEOGRAPHICLIB_DATA=${datadir}/GeographicLib"

PACKAGE_BEFORE_PN += "${PN}-tools"

FILES:${PN}-tools = " \
    ${bindir} \
    ${sbindir} \
"

# The exported CMake targets list the command-line tools, so a consumer's
# find_package() fails on missing files unless bindir is in the sysroot too.
sysroot_stage_all:append() {
    sysroot_stage_dir ${D}${bindir} ${SYSROOT_DESTDIR}${bindir}
}
