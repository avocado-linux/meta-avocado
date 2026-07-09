FILESEXTRAPATHS:append := ":${THISDIR}/files"

DESCRIPTION = "This repository contains the source code for ARM side \
libraries and host binaries used on Raspberry Pi."
LICENSE = "BSD-3-Clause"
LIC_FILES_CHKSUM = "file://LICENCE;md5=0448d6488ef8cc380632b1569ee6d196"

SRC_URI = "\
           git://github.com/${SRCFORK}/userland.git;protocol=https;branch=${SRCBRANCH} \
           file://0001-dtoverlay_main-Fix-configfs-mount-failure.patch \
           file://0002-gcc15-c23-empty-parens-are-no-longer-unspecified-ar.patch \
"

COMPATIBLE_MACHINE = "^rpi$"

SRCBRANCH = "master"
SRCFORK = "raspberrypi"
SRCREV = "a54a0dbb2b8dcf9bafdddfc9a9374fb51d97e976"

# Use the date of the above commit as the package version. Update this when
# SRCREV is changed.
PV = "20210111"


inherit cmake pkgconfig

ASNEEDED = ""
# userland's CMakeLists.txt declares cmake_minimum_required below 3.5, which
# cmake >= 4.0 refuses to configure at all ("Compatibility with CMake < 3.5
# has been removed from CMake"). Set the floor cmake will treat the project
# as targeting, per cmake's own suggested workaround.
EXTRA_OECMAKE = "-DCMAKE_BUILD_TYPE=Release -DCMAKE_EXE_LINKER_FLAGS='-Wl,--no-as-needed' \
                 -DVMCS_INSTALL_PREFIX=${exec_prefix} -DARM64=ON \
                 -DCMAKE_POLICY_VERSION_MINIMUM=3.5 "

# Keep only those libs & bins that are actually
# used during boot EEPROM image update
do_install:append () {
        rm -rf ${D}${bindir}/tvservice
        rm -rf ${D}${bindir}/vchiq_test
        rm -rf ${D}${bindir}/dtmerge
        rm -rf ${D}${prefix}/include
        rm -rf ${D}${prefix}/src
        rm -rf ${D}${libdir}/pkgconfig
        rm -rf ${D}${libdir}/*debug*
        rm -rf ${D}${libdir}/*host*
        rm -rf ${D}${libdir}/*.a
        rm -rf ${D}${bindir}/*post
        rm -rf ${D}${bindir}/*pre

        mkdir -pv ${D}${datadir}
        mv -v ${D}${prefix}/man ${D}${mandir}
}

# Shared libs from userland package build aren't versioned, so we need
# to force the .so files into the runtime package (and keep them
# out of -dev package).
FILES_SOLIBSDEV = ""
INSANE_SKIP:${PN} += "dev-so"
FILES:${PN} += " ${libdir}/*.so "
RDEPENDS:${PN} += "bash"
