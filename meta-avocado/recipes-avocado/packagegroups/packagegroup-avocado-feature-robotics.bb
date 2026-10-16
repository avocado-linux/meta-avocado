DESCRIPTION = "Avocado feature group: robotics and geospatial libraries"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

# asio and websocketpp are header-only, so their -dev package is the only one
# carrying anything an application can build against.
RDEPENDS:${PN} = " \
  asio-dev \
  geographiclib \
  gtsam \
  libtinyxml2 \
  websocketpp-dev \
"
