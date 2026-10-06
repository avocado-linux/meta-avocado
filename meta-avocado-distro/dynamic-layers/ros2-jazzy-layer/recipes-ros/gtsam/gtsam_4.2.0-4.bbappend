# GTSAM 4.2.0 predates the CMake 4 and Boost 1.89 changes in this release:
# - its top-level CMakeLists.txt declares cmake_minimum_required below 3.5, which
#   CMake 4 refuses;
# - it requires the Boost.System component, which Boost 1.89 removed.
# Pinned to the recipe version so a layer bump brings both workarounds up for removal.
FILESEXTRAPATHS:prepend := "${THISDIR}/files:"
SRC_URI += "file://0001-HandleBoost-do-not-require-boost-system.patch"
EXTRA_OECMAKE:append = " -DCMAKE_POLICY_VERSION_MINIMUM=3.5"
