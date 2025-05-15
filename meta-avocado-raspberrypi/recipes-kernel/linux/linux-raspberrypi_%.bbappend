FILESEXTRAPATHS:prepend := "${THISDIR}/files:"
SRC_URI += " \
  file://gpt.cfg \
  file://overlayfs.cfg \
  file://loop.cfg \
  file://squashfs.cfg \
  file://btrfs.cfg \
"
