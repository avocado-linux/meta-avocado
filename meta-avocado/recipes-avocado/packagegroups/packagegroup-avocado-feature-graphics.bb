DESCRIPTION = "Packagegroup for Avocado graphics feature group"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

RDEPENDS:${PN} = " \
  ${@bb.utils.contains('DISTRO_FEATURES', 'opengl', "${OPENGL_PACKAGES}", '', d)} \
"

OPENGL_PACKAGES = " \
  wpewebkit \
  wpebackend-fdo \
  cog \
  cage \
  weston \
  weston-init \
  wayland \
  wayland-utils \
  libdrm-tests \
  xkeyboard-config \
"
