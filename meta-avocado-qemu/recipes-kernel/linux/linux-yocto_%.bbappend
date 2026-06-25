FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI_SHARED = " \
  file://avocado-core.cfg \
  file://avocado-extra.cfg \
"
SRC_URI:append:avocado-qemux86-64 = " \
  ${SRC_URI_SHARED} \
  file://tpm.cfg \
"

SRC_URI:append:avocado-qemuarm64 = " \
  ${SRC_URI_SHARED} \
  file://cpuidle.cfg \
  file://mmc.cfg \
  file://ftpm.cfg \
"

inherit avocado-kernel-feed
inherit avocado-kernel-builtin-provides
require recipes-kernel/linux/avocado-kernel-modules-packagegroup.inc
