DESCRIPTION = "Avocado extensions package image"
LICENSE = "Apache-2.0"

inherit image-packages-only

IMAGE_INSTALL = "\
  packagegroup-avocado-extra \
  packagegroup-ros-world-jazzy \
  ${PKG_EXTRA_INSTALL} \
"
