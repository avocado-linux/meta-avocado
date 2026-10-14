# GTSAM 4.2.0 predates the CMake 4 and Boost 1.89 changes in this release:
# - its top-level CMakeLists.txt declares cmake_minimum_required below 3.5, which
#   CMake 4 refuses;
# - it requires the Boost.System component, which Boost 1.89 removed.
# Pinned to the recipe version so a layer bump brings both workarounds up for removal.
FILESEXTRAPATHS:prepend := "${THISDIR}/files:"
SRC_URI += "file://0001-HandleBoost-do-not-require-boost-system.patch"
EXTRA_OECMAKE:append = " -DCMAKE_POLICY_VERSION_MINIMUM=3.5"

# The feed build runs the SPDX and QA tasks, and the generated recipe fails both.
#
# Licence: package.xml says "BSD", which is neither an SPDX identifier nor a
# common-licence file, so do_create_spdx cannot find a text for it. GTSAM's
# LICENSE.BSD is the three-clause text. LIC_FILES_CHKSUM is unchanged, so the
# checksum still guards the licence file.
LICENSE = "BSD-3-Clause"

# dev-so: meta-ros puts ${ros_libdir}/lib*.so in the main package because ROS
# plugins are plain .so files, but libgtsam.so is a versioned-library symlink.
# The layer's own bbappend moves it to -dev with ${libdir}, which is /usr/lib,
# and these install under the /opt/ros prefix, so that line matches nothing.
FILES:${PN}-dev += " \
    ${ros_libdir}/libgtsam.so \
    ${ros_libdir}/libgtsam_unstable.so \
"

# buildpaths: GTSAM writes its source and build directories into the files it
# installs. config.h carries the example-data directory and is compiled into
# libgtsam, and the generated GTSAMConfig.cmake files name the source tree in a
# branch that only runs from a build tree. Point the first at the installed
# data directory and strip the work directory from the second.
do_configure:prepend() {
    sed -i 's|@GTSAM_SOURCE_DIR@/examples/Data|${datadir}/gtsam/examples/Data|' ${S}/gtsam/config.h.in
}

do_install:append() {
    for f in ${D}${ros_libdir}/cmake/GTSAM/*.cmake ${D}${ros_libdir}/cmake/GTSAM_UNSTABLE/*.cmake; do
        sed -i 's|${WORKDIR}|/usr/src/gtsam|g' "$f"
    done
}
