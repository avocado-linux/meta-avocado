SUMMARY = "Host-side wrapper + ATOC templates for flashing Alif Ensemble OSPI"
DESCRIPTION = "Ships flash-alif.sh and per-machine ATOC JSON templates into \
the avocado SDK so stone-provision-serial.sh can drive the user-supplied Alif \
SETOOLS / app-write-mram to program the OSPI of an Alif Ensemble board. \
SETOOLS itself is closed-source and is NOT shipped here -- the user installs \
it manually inside the SDK container."
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

SRC_URI = " \
    file://flash-alif.sh \
    file://atoc-alif-e8-devkit.json \
    file://README.md \
"

S = "${WORKDIR}"

inherit nativesdk

do_compile[noexec] = "1"

do_install() {
    install -d ${D}${bindir}
    install -m 0755 ${WORKDIR}/flash-alif.sh ${D}${bindir}/avocado-alif-flash

    install -d ${D}${datadir}/avocado-alif-flash
    install -m 0644 ${WORKDIR}/atoc-alif-e8-devkit.json ${D}${datadir}/avocado-alif-flash/atoc-alif-e8-devkit.json
    install -m 0644 ${WORKDIR}/README.md ${D}${datadir}/avocado-alif-flash/README.md
}

FILES:${PN} = "${bindir}/* ${datadir}/avocado-alif-flash"
