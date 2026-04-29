FILESEXTRAPATHS:prepend := "${THISDIR}/ufs:"

do_compile[depends] += "avocado-img-ufs:do_build"

SRC_URI += "file://stone-provision-ufs.sh \
  file://stone-provision-noop.sh \
"

DEPENDS += "jq-native"
AVOCADO_PROVISION_PROFILE = "noop"

do_deploy:append() {
  install -d ${DEPLOYDIR}
  install -m 0755 ${UNPACKDIR}/stone-provision-ufs.sh ${DEPLOYDIR}/stone-provision-ufs.sh
  install -m 0755 ${UNPACKDIR}/stone-provision-noop.sh ${DEPLOYDIR}/stone-provision-noop.sh
}
