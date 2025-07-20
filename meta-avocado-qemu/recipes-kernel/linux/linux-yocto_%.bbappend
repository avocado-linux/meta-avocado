FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI_SHARED = " \
  file://overlayfs.cfg \
  file://erofs.cfg \
  file://gpt.cfg \
  file://loop.cfg \
  file://squashfs.cfg \
  file://dm-verity.cfg.in \
"
SRC_URI:append:avocado-qemux86-64 = " \
  ${SRC_URI_SHARED} \
  file://efi.cfg \
  file://tpm.cfg \
"

SRC_URI:append:avocado-qemuarm64 = " \
  ${SRC_URI_SHARED} \
  file://mmc.cfg \
  file://ftpm.cfg \
"

YOCTO_BUILD_DIR = "${TOPDIR}"
