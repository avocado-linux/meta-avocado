SUMMARY = "jsoncpp 1.9.5 runtime library (libjsoncpp.so.25) for prebuilt binaries"
DESCRIPTION = "The libjsoncpp.so.25 shared library alone, from jsoncpp 1.9.5. \
DeepStream 7.1's prebuilt GStreamer plugins link against that soname, while \
meta-oe ships jsoncpp 1.9.7 (a newer soname). No headers, no development \
files: anything built from source uses the jsoncpp recipe."
HOMEPAGE = "https://github.com/open-source-parsers/jsoncpp"
SECTION = "libs"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://LICENSE;md5=5d73c165a0f9e86a1342f32d19ec5926"

SRCREV = "5defb4ed1a4293b8e2bf641e16b156fb9de498cc"
SRC_URI = "git://github.com/open-source-parsers/jsoncpp;branch=master;protocol=https"

S = "${WORKDIR}/git"

inherit cmake

EXTRA_OECMAKE += "-DBUILD_SHARED_LIBS=ON -DBUILD_STATIC_LIBS=OFF -DBUILD_OBJECT_LIBS=OFF -DJSONCPP_WITH_TESTS=OFF"

# Keep only the versioned runtime library, so this never collides with the
# jsoncpp recipe's headers, unversioned .so link, CMake or pkg-config files
# in a sysroot or an image.
do_install:append() {
    rm -rf ${D}${includedir} ${D}${libdir}/cmake ${D}${libdir}/pkgconfig ${D}${datadir}
    rm -f ${D}${libdir}/libjsoncpp.so
}

# libjsoncpp.so.25 is a link to the versioned file.
FILES:${PN} = "${libdir}/libjsoncpp.so.25* ${libdir}/libjsoncpp.so.${PV}"

# Keep this recipe's package names: debian.bbclass would otherwise rename them
# to libjsoncpp-dev/-dbg/-src, the names the jsoncpp recipe's packages get.
DEBIAN_NOAUTONAME:${PN} = "1"
DEBIAN_NOAUTONAME:${PN}-dev = "1"
DEBIAN_NOAUTONAME:${PN}-dbg = "1"
DEBIAN_NOAUTONAME:${PN}-src = "1"
DEBIAN_NOAUTONAME:${PN}-staticdev = "1"
DEBIAN_NOAUTONAME:${PN}-doc = "1"
