FILESEXTRAPATHS:prepend := "${THISDIR}/files:"
SRC_URI += " \
  file://overlayfs.cfg \
  file://erofs.cfg \
  file://gpt.cfg \
  file://loop.cfg \
  file://squashfs.cfg \
  file://efi.cfg \
  file://tpm.cfg \
  file://dm-verity.cfg.in \
"
YOCTO_BUILD_DIR = "${TOPDIR}"
