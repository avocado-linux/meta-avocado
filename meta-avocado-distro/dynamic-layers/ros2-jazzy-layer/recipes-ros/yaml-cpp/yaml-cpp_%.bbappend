# meta-tegra-community's yaml-cpp-080 (pulled in by deepstream) and this yaml-cpp
# both build a libyaml-cpp library, and debian.bbclass names the development
# packages after the library: each recipe ships libyaml-cpp-dev, -dbg and -src.
# The 0.8 and 0.9 runtime packages differ (libyaml-cpp0.8, libyaml-cpp0.9), but
# a feed that holds both fails do_packagedata on the second recipe:
#
#   Recipe yaml-cpp is trying to install files into a shared area when those
#   files already exist ... (matched in manifest-*-yaml-cpp-080.packagedata)
#
# Keep this recipe's own names for the packages that collide, so the 0.8 set the
# prebuilt deepstream consumers link against is untouched. The runtime library
# still takes its soname-derived name.
DEBIAN_NOAUTONAME:${PN}-dev = "1"
DEBIAN_NOAUTONAME:${PN}-dbg = "1"
DEBIAN_NOAUTONAME:${PN}-src = "1"
DEBIAN_NOAUTONAME:${PN}-staticdev = "1"
