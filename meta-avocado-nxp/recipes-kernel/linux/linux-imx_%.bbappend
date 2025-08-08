FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI += " \
  file://squashfs.cfg \
  file://gpt.cfg \
  file://btrfs.cfg \
"

do_configure:append() {
  cat ../*.cfg >> ${B}/.config
}
