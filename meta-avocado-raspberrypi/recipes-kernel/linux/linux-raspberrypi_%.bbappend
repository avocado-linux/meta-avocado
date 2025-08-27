FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI:append = " \
  file://avocado-boot.cfg \
  file://avocado-modules.cfg \
"
