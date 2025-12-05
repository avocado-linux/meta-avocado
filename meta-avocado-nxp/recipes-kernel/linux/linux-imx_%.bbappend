FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI += " \
  file://avocado-core.cfg \
  file://avocado-extra.cfg \
"

do_configure:append() {
  cat ${WORKDIR}/*.cfg >> ${B}/.config
}
