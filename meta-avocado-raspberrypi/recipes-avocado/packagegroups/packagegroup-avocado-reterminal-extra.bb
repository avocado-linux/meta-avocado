DESCRIPTION = "Packagegroup for extra inclusions in Avocado reTerminal images"
LICENSE = "Apache-2.0"

inherit features_check

IMAGE_FEATURES += ""
REQUIRED_DISTRO_FEATURES = ""

inherit packagegroup

RDEPENDS:${PN} = " \
  kernel-module-ili9881d \
  kernel-module-seeed-mipi-dsi \
  kernel-module-ltr30x \
  kernel-module-rtc-pcf8563w \
"
