FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI:append = " \
  file://gpt.cfg \
  file://overlayfs.cfg \
  file://loop.cfg \
  file://squashfs.cfg \
  file://btrfs.cfg \
"

SRC_URI:append:reterminal = " file://reterminal.cfg"
SRC_URI:append:reterminal-dm = " file://reterminal.cfg"
