SUMMARY = "WiringPi-compatible Python bindings for RUBIK Pi 3"
DESCRIPTION = "Python module wrapping the wiringrp C library; drop-in for code \
written against the RPi.WiringPi-Python module."
LICENSE = "CLOSED"

# Source: https://github.com/rubikpi-ai/meta-rubikpi-bsp @ 227631ce94bb
DEPENDS += "libxcrypt wiringrp python3 swig-native"

# The patch is wiringrp_3.12.bb's - same WiringRP SRCREV, same C23 build
# failure - so it is shared from this directory's files/ rather than copied.
# setup.py compiles the WiringPi/ subtree itself (it does not just link the
# staged libwiringPi), which is why this recipe needs it too. patchdir points
# at that subtree because the patch paths are relative to the WiringRP repo
# root, not to S (= .../git/python).
FILESEXTRAPATHS:prepend := "${THISDIR}/files:"
SRC_URI = " \
    git://github.com/rubikpi-ai/WiringRP-Python.git;protocol=https;branch=main;name=python;destsuffix=git/python \
    git://github.com/rubikpi-ai/WiringRP.git;protocol=https;branch=main;name=c;destsuffix=git/python/WiringPi \
    file://0001-wiringPi-call-GetRP1Memory-with-no-arguments.patch;patchdir=${UNPACKDIR}/git/python/WiringPi \
    file://0002-wiringpi.i-use-SWIG_AppendOutput-in-the-argout-typemap.patch \
"

SRCREV_python = "8b797fdde07d564f648bddba900507ac241eba6e"
SRCREV_c = "4bfb0de9f6605978e55ee2e89374b2eb2a84358d"

SRCREV_FORMAT = "python_c"

S = "${UNPACKDIR}/git/python"

inherit setuptools3 pkgconfig

CFLAGS:append = " -I${STAGING_INCDIR}/wiringpi"
LDFLAGS:append = " -L${STAGING_LIBDIR} -lwiringPi -lwiringPiDev"

export WIRINGPI_LIB_DIR = "${STAGING_LIBDIR}"
export WIRINGPI_INC_DIR = "${STAGING_INCDIR}/wiringpi"

SETUPTOOLS_BUILD_ARGS:append = " install"

FILES:${PN} += "${libdir}"
FILES:${PN} += "${includedir}"
