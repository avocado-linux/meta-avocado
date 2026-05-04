FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

SRC_URI:append:stm32mp25-disco = " \
  file://avocado.cfg \
  file://env-nowhere.cfg \
"
