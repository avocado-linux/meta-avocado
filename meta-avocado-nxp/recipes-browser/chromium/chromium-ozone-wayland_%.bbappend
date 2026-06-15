# Ensure libgbm is available for runtime EGL operations on all i.MX targets
DEPENDS:append:avocado-imx = " virtual/libgbm"

# i.MX8MP uses Vivante's libgbm-imx which is not compatible with Chromium's
# system minigbm integration. Disable system minigbm to use Chromium's
# bundled minigbm instead.
#
# This fixes linker errors like:
#   undefined symbol: gl::NativeViewGLSurfaceEGL::NativeViewGLSurfaceEGL(...)
#
# The Vivante GPU provides libgbm but not minigbm, and the EGL surface
# implementation requires consistent GBM handling.
#
# Keyed on the i.MX8MP SoC override so it covers every i.MX8MP board (NXP EVK,
# CompuLab UCM-iMX8M-Plus, future boards). NOTE: the bare "mx8mp" token is NOT
# a usable override -- imx-base.inc's MACHINEOVERRIDES_EXTENDER rewrites the SoC
# tokens into BSP-suffixed forms (mx8mp-generic-bsp / mx8mp-nxp-bsp) and drops
# the bare ones. "mx8mp-generic-bsp" is present for all i.MX8MP regardless of
# IMX_DEFAULT_BSP. (Verify with: bitbake -e chromium-ozone-wayland | grep ^OVERRIDES=)
GN_ARGS:append:mx8mp-generic-bsp = " use_system_minigbm=false"
