FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI += " \
  file://avocado-core.cfg \
  file://avocado-extra.cfg \
  file://avocado-wireless.cfg \
"

do_configure:append() {
  cat ${WORKDIR}/*.cfg >> ${B}/.config
}

require recipes-kernel/linux/avocado-kernel-modules-packagegroup.inc
