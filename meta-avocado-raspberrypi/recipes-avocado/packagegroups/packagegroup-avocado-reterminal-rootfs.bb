DESCRIPTION = "Packagegroup for rootfs inclusions in Avocado reTerminal images"
LICENSE = "Apache-2.0"

inherit features_check

IMAGE_FEATURES += ""
REQUIRED_DISTRO_FEATURES = ""

inherit packagegroup

PREFERRED_PROVIDER_virtual/dtb = "reterminal-devicetree"

RDEPENDS:${PN} = " \
  reterminal-devicetree \
"
