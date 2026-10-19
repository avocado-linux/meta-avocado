# libnvvpi.so.4 links libEGL_nvidia.so.0, which tegra-libraries-eglcore ships.
# The meta-tegra recipe lists that package in DEPENDS (so it builds) but not in
# RDEPENDS, and avocado treats the resulting file-rdeps QA error as fatal:
#
#   /opt/nvidia/vpi4/lib/aarch64-linux-gnu/libnvvpi.so.4.1.3 contained in
#   package libnvvpi4 requires libEGL_nvidia.so.0()(64bit), but no providers
#   found in RDEPENDS:libnvvpi4?
#
# Declare the runtime dependency, so an image that installs libnvvpi4 also gets
# the library it loads.
RDEPENDS:${PN} += "tegra-libraries-eglcore"

# tegra-libraries-eglcore lists libEGL_nvidia.so.0 under both /usr/lib and
# /usr/lib/aarch64-linux-gnu/tegra-egl, so the shlib resolver matches two
# directories and fails with "Multiple shlib providers" before the RDEPENDS
# above is consulted. Skip the resolver for this one library.
PRIVATE_LIBS:${PN} += "libEGL_nvidia.so.0"
