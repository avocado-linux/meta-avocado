SUMMARY = "Activity Indicators for Modern C++"
DESCRIPTION = "Header-only C++17 library providing thread-safe progress bars and spinners."
HOMEPAGE = "https://github.com/p-ranav/indicators"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://LICENSE;md5=82ce504a4a2009f1a25f8b28d8c48313"

PV = "2.3+git"
SRCREV = "ac6c93ea2b1f97a220d10a0729a625b3f51e320b"
SRC_URI = "git://github.com/p-ranav/indicators.git;branch=master;protocol=https"

S = "${WORKDIR}/git"

inherit cmake

# Header-only library: no binaries to package, just install the headers.
EXTRA_OECMAKE = "-DBUILD_TESTS=OFF -DBUILD_DEMO=OFF"

FILES:${PN} = "${datadir}/licenses"
FILES:${PN}-dev = "${includedir} ${libdir}/cmake ${libdir}/pkgconfig"

ALLOW_EMPTY:${PN} = "1"

BBCLASSEXTEND = "native nativesdk"
