FILESEXTRAPATHS:prepend := "${THISDIR}/${BPN}:"
SRC_URI:remove = "file://repackage-lely-core.patch"
SRC_URI:append = " file://0001-repackage-lely-core.patch"

SRCREV_upstream = "7824cbb2ac08d091c4fa2fb397669b938de9e3f5"

DEPENDS += "lely-core lely-core-native"

# CMake Error:
# Running
#  'ninja' '-C' 'TOPDIR/tmp-glibc/work/core2-64-oe-linux/lely-core-libraries/0.2.7-1-r0/build' '-t' 'recompact'
# failed with:
#  ninja: error: build.ninja:185: bad $-escape (literal $ must be written as $$)
#
# This is caused by a hard-coded command that violates ninja syntax: cd <DIR> && $(MAKE)
OECMAKE_GENERATOR = "Unix Makefiles"

PACKAGES += "python3-cogen"

FILES:python3-cogen = " \
    ${libdir}/python*/site-packages/cogen/cogen.py \
    ${libdir}/cogen/cogen \
    ${bindir}/cogen \
"

do_install:append() {
    sed -i -e '1s|^#!.*|#!/usr/bin/env python3|' ${D}/opt/ros/jazzy/bin/cogen
    sed -i -e '1s|^#!.*|#!/usr/bin/env python3|' ${D}/opt/ros/jazzy/lib/cogen/cogen
}

BBCLASSEXTEND = "native nativesdk"
