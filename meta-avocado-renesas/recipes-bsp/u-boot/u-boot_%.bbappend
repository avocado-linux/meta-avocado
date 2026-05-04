FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

SRC_URI:append = " \
  file://avocado.cfg \
  file://env-nowhere.cfg \
  file://fastboot.cfg \
"
