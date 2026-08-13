DESCRIPTION = "Packagegroup for Avocado graphics feature group"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

RDEPENDS:${PN} = " \
  ${@bb.utils.contains('DISTRO_FEATURES', 'opengl', "${OPENGL_PACKAGES}", '', d)} \
"

# scarthgap also lists wpewebkit, wpebackend-fdo and cog here. All three come
# from meta-webkit, which has no wrynose branch, so kas/feature/graphics.yml
# does not provision that layer and naming them here would make the group
# unbuildable rather than merely smaller. Restore with the layer.
OPENGL_PACKAGES = " \
  cage \
  weston \
  weston-init \
  wayland \
  wayland-utils \
  libdrm-tests \
  xkeyboard-config \
"
