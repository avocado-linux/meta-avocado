do_compile[depends] += "avocado-img-tegraflash:do_build"

SRC_URI += " \
  file://stone-provision-tegraflash.sh \
  file://stone-provision-noop.sh \
"

DEPENDS += " jq-native"
AVOCADO_PROVISION_PROFILE = "noop"

do_deploy:append() {
  install -d ${DEPLOYDIR}
  install -m 0755 ${WORKDIR}/stone-provision-tegraflash.sh ${DEPLOYDIR}/stone-provision-tegraflash.sh
  install -m 0755 ${WORKDIR}/stone-provision-noop.sh ${DEPLOYDIR}/stone-provision-noop.sh
}
