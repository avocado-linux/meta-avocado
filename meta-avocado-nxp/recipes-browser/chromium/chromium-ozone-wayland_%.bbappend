# Ensure libgbm is available for runtime EGL operations on all i.MX targets
DEPENDS:append:avocado-imx = " virtual/libgbm"

# meta-imx ships its own libgbm (Vivante's libgbm-imx on i.MX8MP, the Mali
# stack on i.MX95) which is not compatible with Chromium's system minigbm
# integration: the GPU provides libgbm but not minigbm, and the EGL surface
# implementation requires consistent GBM handling. Disable system minigbm to
# use Chromium's bundled minigbm instead.
#
# This fixes linker errors like:
#   undefined symbol: gl::NativeViewGLSurfaceEGL::NativeViewGLSurfaceEGL(...)
#
# Keyed on the per-SoC "<soc>-generic-bsp" override so it covers every board of
# that SoC (e.g. NXP EVK, CompuLab UCM-iMX8M-Plus, i.MX95 FRDM, future boards).
# NOTE: the bare "mx8mp"/"mx95" tokens are NOT usable overrides -- imx-base.inc's
# MACHINEOVERRIDES_EXTENDER rewrites the SoC tokens into BSP-suffixed forms
# (<soc>-generic-bsp / <soc>-nxp-bsp) and drops the bare ones. "<soc>-generic-bsp"
# is present for all boards of that SoC regardless of IMX_DEFAULT_BSP.
# (Verify with: bitbake -e chromium-ozone-wayland | grep ^OVERRIDES=)
GN_ARGS:append:mx8mp-generic-bsp = " use_system_minigbm=false"
GN_ARGS:append:mx95-generic-bsp = " use_system_minigbm=false"
