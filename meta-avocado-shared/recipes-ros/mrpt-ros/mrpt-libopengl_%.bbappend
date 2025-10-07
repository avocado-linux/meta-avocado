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
    rosidl-typesupport-fastrtps-c-native \
    rosidl-typesupport-fastrtps-cpp-native \
    rosidl-generator-c-native \
    rosidl-generator-cpp-native \
"

inherit python3native
inherit pkgconfig
inherit ros_ament_cmake

# Add target dependencies for rosidl typesupport packages
ROS_BUILD_DEPENDS += " \
    ament-cmake-libraries \
    ament-cmake-export-definitions \
    ament-cmake-export-include-directories \
    ament-cmake-export-interfaces \
    ament-cmake-export-libraries \
    ament-cmake-export-link-flags \
    ament-cmake-export-targets \
    ament-cmake-gen-version-h \
    ament-cmake-python \
    ament-cmake-target-dependencies \
    ament-cmake-include-directories \
    ament-cmake-test \
    ament-cmake-version \
    rosidl-adapter \
"

CFLAGS += "-I${STAGING_DIR_TARGET}/usr/include"

do_configure:prepend() {
    # Inject eigen3 configuration and toolchain file into the ExternalProject CMAKE_ARGS
    # This ensures the inner MRPT build can find the system eigen3 and use the correct toolchain
    sed -i "/CMAKE_ARGS/a\\    -DEigen3_DIR=${STAGING_DATADIR}/eigen3/cmake" ${S}/CMakeLists.txt
    sed -i "/CMAKE_ARGS/a\\    -DCMAKE_TOOLCHAIN_FILE=${WORKDIR}/toolchain.cmake" ${S}/CMakeLists.txt
}
