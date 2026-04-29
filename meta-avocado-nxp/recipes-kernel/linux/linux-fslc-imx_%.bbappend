FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI += " \
  file://avocado-core.cfg \
  file://avocado-extra.cfg \
  file://avocado-wireless.cfg \
  file://avocado-netfilter.cfg \
  file://avocado-usb-serial.cfg \
"

do_configure:append() {
  cat ${WORKDIR}/*.cfg >> ${B}/.config
}

inherit avocado-kernel-feed
inherit avocado-kernel-builtin-provides
require recipes-kernel/linux/avocado-kernel-modules-packagegroup.inc
