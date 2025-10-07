# Fix BSD license for SPDX
LICENSE = "BSD-3-Clause"

SRCREV = "957ac2142091b6af49e9d131b05aface4cdc6d8b"

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
    # This ensures that nested builds (like assimp, libfyaml) can find standard headers
    sed -i "/CMAKE_ARGS/a\\    -DCMAKE_SYSROOT=${STAGING_DIR_TARGET}" ${S}/CMakeLists.txt
}

# Fix libfyaml cross-compilation by directly modifying its CMakeLists.txt
# The libfyaml ExternalProject doesn't properly inherit CMAKE_C_FLAGS, so we inject them directly
do_compile:prepend() {
    LIBFYAML_CMAKE="${B}/mrpt-build/src/mrpt/3rdparty/libfyaml/CMakeLists.txt"

    if [ -f "${LIBFYAML_CMAKE}" ]; then
        bbnote "Patching libfyaml CMakeLists.txt to fix cross-compilation sysroot"

        # Inject CMAKE_C_FLAGS and CMAKE_CXX_FLAGS with sysroot right after project() declaration
        # This ensures all C/C++ compilation commands include the --sysroot flag
        sed -i '/^project(libfyaml/a \
# Cross-compilation fix: Ensure sysroot is propagated to all compilation commands\
if(NOT DEFINED CMAKE_C_FLAGS)\
    set(CMAKE_C_FLAGS "")\
endif()\
if(NOT DEFINED CMAKE_CXX_FLAGS)\
    set(CMAKE_CXX_FLAGS "")\
endif()\
set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} --sysroot='"${STAGING_DIR_TARGET}"'")\
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} --sysroot='"${STAGING_DIR_TARGET}"'")' "${LIBFYAML_CMAKE}"

        bbnote "Successfully patched ${LIBFYAML_CMAKE}"
    else
        bbwarn "libfyaml CMakeLists.txt not found at ${LIBFYAML_CMAKE} - may have already been configured"
    fi
}

