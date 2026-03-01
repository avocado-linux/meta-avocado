OS_RELEASE_FIELDS:append = " VENDOR_NAME VENDOR_URL DOCUMENTATION_URL BUILD_ID VERSION_CODENAME"

VENDOR_NAME = "${DISTRO_VENDOR}"
VENDOR_URL = "${DISTRO_VENDOR_URL}"
DOCUMENTATION_URL = "${DISTRO_DOCUMENTATION_URL}"
BUILD_ID = "${@d.getVar('BUILD_ID') or '0'}"
VERSION_CODENAME = "${DISTRO_CODENAME}"

inherit deploy

do_deploy() {
    install -d ${DEPLOYDIR}
    install -m 0644 ${WORKDIR}/${PN}-${PV}/os-release ${DEPLOYDIR}/os-release
}

addtask deploy after do_compile before do_package
