FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"
FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}/env:"

SRC_URI:append = " \
  file://avocado.cfg \
  file://env-mmc.cfg \
"

MKENVIMAGE_EXTRA_ARGS = "-r"
