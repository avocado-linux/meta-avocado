# Based on the superflore-generated recipe in meta-ros (2.14.0-1), moved to 2.16.0-1.
# meta-ros has no 2.16.0 recipes yet and 2.14.0's libmavconn does not build against the
# asio in this release: upstream moved it off asio::io_service in 2.15.0.
# Dependencies follow the 2.16.0 package.xml. Drop these files once meta-ros carries
# mavros 2.16.0 or later.
#
# Copyright Open Source Robotics Foundation

inherit ros_distro_jazzy
inherit ros_superflore_generated

DESCRIPTION = "MAVROS -- MAVLink extendable communication node for ROS     with proxy for Ground Control Station."
AUTHOR = "Vladimir Ermakov <vooon341@gmail.com>"
ROS_AUTHOR = "Vladimir Ermakov <vooon341@gmail.com>"
HOMEPAGE = "http://wiki.ros.org/mavros"
SECTION = "devel"
# Original license in package.xml, joined with "&" when multiple license tags were used:
#         "GPLv3 & LGPLv3 & BSD"
# "BSD" in package.xml has no licence text in the release repository; treated as BSD-3-Clause
# for the feed build, an assumption not verified against the upstream licence.
LICENSE = "GPL-3.0-only & LGPL-3.0-only & BSD-3-Clause"
LIC_FILES_CHKSUM = "file://package.xml;beginline=13;endline=13;md5=1e7b3bcc2e271699c77c769685058cbe"

ROS_CN = "mavros"
ROS_BPN = "mavros"

ROS_BUILD_DEPENDS = " \
    angles \
    console-bridge \
    diagnostic-msgs \
    diagnostic-updater \
    eigen-stl-containers \
    geographic-msgs \
    geographiclib \
    geometry-msgs \
    libeigen \
    libmavconn \
    mavlink \
    mavros-msgs \
    message-filters \
    nav-msgs \
    pluginlib \
    rcl \
    rclcpp \
    rclcpp-components \
    rcpputils \
    sensor-msgs \
    std-msgs \
    std-srvs \
    tf2-eigen \
    tf2-ros \
    trajectory-msgs \
"

ROS_BUILDTOOL_DEPENDS = " \
    ament-cmake-native \
    ament-cmake-python-native \
    eigen3-cmake-module-native \
"

ROS_EXPORT_DEPENDS = " \
    console-bridge \
    diagnostic-msgs \
    diagnostic-updater \
    eigen-stl-containers \
    geographic-msgs \
    geographiclib \
    geometry-msgs \
    libeigen \
    libmavconn \
    mavlink \
    mavros-msgs \
    message-filters \
    nav-msgs \
    pluginlib \
    rcl \
    rclcpp \
    rclcpp-components \
    rcpputils \
    sensor-msgs \
    std-msgs \
    std-srvs \
    tf2-eigen \
    tf2-ros \
    trajectory-msgs \
"

ROS_BUILDTOOL_EXPORT_DEPENDS = " \
    eigen3-cmake-module-native \
"

ROS_EXEC_DEPENDS = " \
    console-bridge \
    diagnostic-msgs \
    diagnostic-updater \
    eigen-stl-containers \
    geographic-msgs \
    geometry-msgs \
    libmavconn \
    mavros-msgs \
    message-filters \
    nav-msgs \
    pluginlib \
    python3-click \
    rcl \
    rclcpp \
    rclcpp-components \
    rclpy \
    rcpputils \
    rosidl-default-runtime \
    sensor-msgs \
    std-msgs \
    std-srvs \
    tf2-eigen \
    tf2-ros \
    trajectory-msgs \
"

# Currently informational only -- see http://www.ros.org/reps/rep-0149.html#dependency-tags.
ROS_TEST_DEPENDS = " \
    ament-cmake-gmock \
    ament-cmake-gtest \
    ament-cmake-pytest \
    ament-lint-auto \
    ament-lint-common \
    gtest \
"

DEPENDS = "${ROS_BUILD_DEPENDS} ${ROS_BUILDTOOL_DEPENDS}"
# Bitbake doesn't support the "export" concept, so build them as if we needed them to build this package (even though we actually
# don't) so that they're guaranteed to have been staged should this package appear in another's DEPENDS.
DEPENDS += "${ROS_EXPORT_DEPENDS} ${ROS_BUILDTOOL_EXPORT_DEPENDS}"

RDEPENDS:${PN} += "${ROS_EXEC_DEPENDS}"

# The package ships two scripts the file-rdeps check ties to interpreters:
# install_geographiclib_datasets.sh needs /bin/bash and the mav command needs
# /usr/bin/python3, which python3-core ships. Neither is in the 2.16.0 package.xml
# exec dependencies.
RDEPENDS:${PN} += "bash python3-core"

# matches with: https://github.com/ros2-gbp/mavros-release/archive/release/jazzy/mavros/2.16.0-1.tar.gz
ROS_BRANCH ?= "branch=release/jazzy/mavros"
SRC_URI = "git://github.com/ros2-gbp/mavros-release;${ROS_BRANCH};protocol=https"
SRCREV = "819f96bc4224aee602b471f459e765f77690e66b"

ROS_BUILD_TYPE = "ament_cmake"

inherit ros_${ROS_BUILD_TYPE}
