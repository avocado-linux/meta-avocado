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
GN_ARGS:append:imx8mp-evk = " use_system_minigbm=false"
