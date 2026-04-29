OS_RELEASE_FIELDS:append = " VENDOR_NAME VENDOR_URL DOCUMENTATION_URL BUILD_ID VERSION_CODENAME"

VENDOR_NAME = "${DISTRO_VENDOR}"
VENDOR_URL = "${DISTRO_VENDOR_URL}"
DOCUMENTATION_URL = "${DISTRO_DOCUMENTATION_URL}"
BUILD_ID ?= "0"
VERSION_CODENAME = "${DISTRO_CODENAME}"

inherit deploy

do_deploy() {
    install -d ${DEPLOYDIR}
    # Upstream do_compile writes to ${B}/os-release. Wrynose stopped
    # auto-creating ${WORKDIR}/${PN}-${PV} for recipes with no SRC_URI
    # (do_fetch/do_unpack are noexec for os-release), so the old
    # ${WORKDIR}/${PN}-${PV}/os-release path is gone.
    install -m 0644 ${B}/os-release ${DEPLOYDIR}/os-release
}

addtask deploy after do_compile before do_package
