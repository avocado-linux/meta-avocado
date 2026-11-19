FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI_SHARED = " \
  file://avocado-core.cfg \
  file://avocado-extra.cfg \
"
SRC_URI:append:avocado-qemux86-64 = " \
  ${SRC_URI_SHARED} \
  file://tpm.cfg \
  file://x86-efi.cfg \
"

SRC_URI:append:avocado-qemuarm64 = " \
  ${SRC_URI_SHARED} \
  file://cpuidle.cfg \
  file://mmc.cfg \
  file://ftpm.cfg \
"

# DEBUG_KERNEL is off on these machines, so the debug-info switch would also
# turn on the runtime debug options the BSP requests. Keep them off.
AVOCADO_KERNEL_DEBUGINFO_RUNTIME_OFF:avocado-qemux86-64 = "1"
AVOCADO_KERNEL_DEBUGINFO_RUNTIME_OFF:avocado-qemuarm64 = "1"

inherit avocado-kernel-feed
inherit avocado-kernel-builtin-provides
require recipes-kernel/linux/avocado-kernel-modules-packagegroup.inc
