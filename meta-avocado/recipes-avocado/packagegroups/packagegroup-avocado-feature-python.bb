DESCRIPTION = "Packagegroup for the Avocado python feature"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

RDEPENDS:${PN} = " \
  ${PYTHON_PACKAGES} \
"

PYTHON_PACKAGES = " \
  python3-pyyaml \
  python3-pip \
  python3-flask \
  python3-werkzeug \
  python3-jinja2 \
  python3-markupsafe \
  python3-itsdangerous \
  python3-click \
  python3-opencv \
  python3-spidev \
  python3-smbus \
  python3-cryptography \
  python3-distro \
  python3-paho-mqtt \
  python3-periphery \
  python3-posix-ipc \
  python3-psutil \
  python3-pycurl \
  python3-pyserial \
  python3-requests \
  python3-smbus2 \
  python3-tzdata \
"
