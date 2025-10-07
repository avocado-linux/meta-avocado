FILESEXTRAPATHS:prepend := "${THISDIR}/${BPN}:"

# Fix BSD license for SPDX
LICENSE = "BSD-3-Clause"

ROS_BUILDTOOL_DEPENDS += " \
    ament-package-native \
    ament-cmake-core-native \
    ament-cmake-libraries-native \
    ament-cmake-export-definitions-native \
    ament-cmake-export-interfaces-native \
    ament-cmake-export-include-directories-native \
    ament-cmake-export-link-flags-native \
    ament-cmake-export-targets-native \
    ament-cmake-gen-version-h-native \
    ament-cmake-export-libraries-native \
    ament-cmake-export-dependencies-native \
    ament-cmake-test-native \
    ament-cmake-gtest-native \
    ament-cmake-pytest-native \
    ament-cmake-ros-native \
    rosidl-adapter-native \
    rosidl-typesupport-c-native \
    rosidl-typesupport-cpp-native \
    rosidl-typesupport-introspection-c-native \
    rosidl-typesupport-introspection-cpp-native \
    rosidl-cmake-native \
    rosidl-default-generators-native \
    rosidl-generator-c-native \
    rosidl-generator-cpp-native \
    rosidl-generator-py-native \
    python3-numpy-native \
    git-native \
"

# Inject Eigen3 configuration and toolchain file into the ExternalProject CMAKE_ARGS
# This ensures the inner MRPT build can find Eigen3 and use the correct cross-compilation settings
do_configure:prepend() {
    # Get the Eigen3 config directory from the sysroot
    EIGEN3_CMAKE_DIR="${STAGING_DIR_TARGET}/usr/lib/cmake/eigen3"

    # Add Eigen3_DIR to CMAKE_ARGS so the inner build can find Eigen3
    sed -i "/CMAKE_ARGS/a\\    -DEigen3_DIR=${EIGEN3_CMAKE_DIR}" ${S}/CMakeLists.txt

    # Also inject the toolchain file to ensure proper cross-compilation
    # This is critical for the ExternalProject to use the correct compiler and sysroot
    sed -i "/CMAKE_ARGS/a\\    -DCMAKE_TOOLCHAIN_FILE=${WORKDIR}/toolchain.cmake" ${S}/CMakeLists.txt

    # Explicitly set CMAKE_SYSROOT for nested ExternalProjects
    sed -i "/CMAKE_ARGS/a\\    -DCMAKE_SYSROOT=${STAGING_DIR_TARGET}" ${S}/CMakeLists.txt
}

# Fix nanogui font finding for cross-compilation
# The nanogui ExternalProject is downloaded by CMake during do_configure, so we must patch it
# before compilation starts rather than during the standard do_patch task
do_compile:prepend() {
    NANOGUI_CMAKE="${B}/mrpt-build/src/mrpt/3rdparty/nanogui/CMakeLists.txt"

    if [ -f "${NANOGUI_CMAKE}" ]; then
        bbnote "Patching nanogui CMakeLists.txt to add NO_CMAKE_FIND_ROOT_PATH for font files"

        # The truetype fonts are provided locally with an absolute path to find them.
        # Without NO_CMAKE_FIND_ROOT_PATH, they cannot be found because the
        # CMAKE_PREFIX_PATH is applied to the suggested path.
        # We add NO_CMAKE_FIND_ROOT_PATH to each find_file() call for the font files.
        sed -i 's/find_file(ENTYPO_TTF_FILE\(.*\)REQUIRED)/find_file(ENTYPO_TTF_FILE\1REQUIRED NO_CMAKE_FIND_ROOT_PATH)/' "${NANOGUI_CMAKE}"
        sed -i 's/find_file(ROBOTO_BOLD_TTF_FILE\(.*\)REQUIRED)/find_file(ROBOTO_BOLD_TTF_FILE\1REQUIRED NO_CMAKE_FIND_ROOT_PATH)/' "${NANOGUI_CMAKE}"
        sed -i 's/find_file(ROBOTO_REGULAR_TTF_FILE\(.*\)REQUIRED)/find_file(ROBOTO_REGULAR_TTF_FILE\1REQUIRED NO_CMAKE_FIND_ROOT_PATH)/' "${NANOGUI_CMAKE}"

        bbnote "Successfully patched ${NANOGUI_CMAKE}"
    else
        bbwarn "nanogui CMakeLists.txt not found at ${NANOGUI_CMAKE} - may have already been configured"
    fi
}

