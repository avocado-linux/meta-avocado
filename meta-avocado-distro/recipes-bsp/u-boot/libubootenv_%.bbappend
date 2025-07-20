FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"
SRC_URI:append:class-target:bootvars-ubootenv = " \
  file://fw_env.config \
"

inherit deploy

FILES:${PN}:append:class-target:bootvars-ubootenv = "${sysconfdir}/fw_env.config"

do_install:append:class-target:bootvars-ubootenv() {
  install -d ${D}${sysconfdir}
  install -m 644 ${WORKDIR}/fw_env.config ${D}${sysconfdir}/fw_env.config
}

inherit deploy

do_deploy:bootvars-ubootenv() {
    install -m 644 ${WORKDIR}/fw_env.config ${DEPLOYDIR}/fw_env.config
}

do_deploy() {
    :
}

addtask deploy after do_compile before do_install
