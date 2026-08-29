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

# meta-freescale pins libdrm to 2.4.127.imx on every NXP BSP; the wlroots 0.20
# behind meta-wayland's default cage needs >= 2.4.129, so its meson setup fails
# there. cage-0.2 is the same kiosk on wlroots 0.19 (libdrm >= 2.4.122).
OPENGL_PACKAGES:remove:imx-nxp-bsp = "cage"
OPENGL_PACKAGES:append:imx-nxp-bsp = " cage-0.2"
