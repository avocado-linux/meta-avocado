do_compile[depends] += "avocado-img-ufs:do_build"

DEPENDS += "jq-native"
AVOCADO_PROVISION_PROFILE = "noop"

SRC_URI:append:stone-ufs = " \
    file://stone-provision-ufs.sh \
"

SRC_URI:append:stone-noop = " \
    file://stone-provision-noop.sh \
"

do_deploy:append:stone-ufs() {
    install -d ${DEPLOYDIR}
    install -m 0755 ${WORKDIR}/stone-provision-ufs.sh ${DEPLOYDIR}/stone-provision-ufs.sh
}

do_deploy:append:stone-noop() {
    install -d ${DEPLOYDIR}
    install -m 0755 ${WORKDIR}/stone-provision-noop.sh ${DEPLOYDIR}/stone-provision-noop.sh
}
