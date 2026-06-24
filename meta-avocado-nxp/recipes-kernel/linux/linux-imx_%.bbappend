FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI += " \
  file://avocado-core.cfg \
  file://avocado-extra.cfg \
  file://avocado-wireless.cfg \
  file://avocado-netfilter.cfg \
  file://avocado-usb-serial.cfg \
"

SRC_URI:append:avocado-imx93-frdm = " \
  file://imx93-frdm/dm-crypt.cfg \
"

do_configure:append() {
  cat ${UNPACKDIR}/*.cfg >> ${B}/.config
  for f in ${UNPACKDIR}/imx93-frdm/*.cfg; do
    [ -e "$f" ] && cat "$f" >> ${B}/.config
  done
}

inherit avocado-kernel-feed
inherit avocado-kernel-builtin-provides
require recipes-kernel/linux/avocado-kernel-modules-packagegroup.inc
