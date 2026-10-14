DESCRIPTION = "Avocado feature group: robotics and geospatial libraries"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

# asio and websocketpp are header-only, so their -dev package is the only one
# carrying anything an application can build against.
RDEPENDS:${PN} = " \
  asio-dev \
  cpp-semver-dev \
  geographiclib \
  graphicsmagick \
  graphicsmagick-dev \
  gtsam \
  libccd \
  libccd-dev \
  libtinyxml2 \
  proj \
  proj-dev \
  urdfdom-headers \
  urdfdom-headers-dev \
  websocketpp-dev \
"

# Libraries a ROS 2 *_vendor package would otherwise download and build itself.
# With them in the feed, the vendor package finds the library and builds
# nothing. gz-cmake3 is CMake modules only, so its -dev package is the one that
# carries files.
RDEPENDS:${PN} += " \
  console-bridge \
  console-bridge-dev \
  foonathan-memory \
  foonathan-memory-dev \
  gz-cmake3-dev \
  gz-math7 \
  gz-math7-dev \
  gz-utils2 \
  gz-utils2-dev \
  libyaml \
  libyaml-dev \
  orocos-kdl \
  orocos-kdl-dev \
"
