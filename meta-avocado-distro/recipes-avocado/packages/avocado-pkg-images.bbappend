FILESEXTRAPATHS:prepend := "${@':'.join(['%s/stone' % layer for layer in d.getVar('BBLAYERS').split()])}:"

SRC_URI = "file://stone-${MACHINE_SHORT_NAME}.json"

inherit deploy

do_deploy() {
    install -d ${DEPLOYDIR}
    install -m 0644 ${WORKDIR}/stone-${MACHINE_SHORT_NAME}.json ${DEPLOYDIR}/stone-${MACHINE_SHORT_NAME}.json
}

addtask deploy after do_compile before collect_artifacts
