FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI += " \
  file://avocado-core.cfg \
  file://avocado-extra.cfg \
  file://avocado-wireless.cfg \
  file://avocado-netfilter.cfg \
  file://avocado-usb-serial.cfg \
  file://caam.cfg \
"

do_configure:append() {
  cat ${UNPACKDIR}/*.cfg >> ${B}/.config
}

# dm-crypt/dm-verity capability, unconditional - see avocado-security-kernel.inc
# for why capability is never gated on a DISTRO_FEATURE. The fragments land in
# UNPACKDIR and are merged by the `cat ${UNPACKDIR}/*.cfg` in do_configure:append
# below, same as every other fragment this bbappend carries.
require recipes-kernel/linux/avocado-security-kernel.inc

inherit avocado-kernel-feed
inherit avocado-kernel-builtin-provides
require recipes-kernel/linux/avocado-kernel-modules-packagegroup.inc
