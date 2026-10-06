SUMMARY = "Call-stack profiler for Python"
HOMEPAGE = "https://github.com/joerick/pyinstrument"
LICENSE = "BSD-3-Clause"
LIC_FILES_CHKSUM = "file://LICENSE;md5=e0510e6ecbcdcb87e3cf13147f37f166"

SRC_URI[sha256sum] = "93dc5576fa90bb267c46d864712329e8e057f51a6b15d0b4f917558d82066ba7"

# Has a C extension (pyinstrument/low_level/stat_profile) — needs the toolchain.
inherit pypi python_setuptools_build_meta

RDEPENDS:${PN} += "python3-json"

BBCLASSEXTEND = "native nativesdk"
