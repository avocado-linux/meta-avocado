SUMMARY = "A simple interface to GPIO devices with Raspberry Pi"
DESCRIPTION = "GPIO Zero is a simple library for interacting with GPIO devices. \
It provides a simple, intuitive interface to GPIO devices such as LEDs, buttons, \
sensors, and more on the Raspberry Pi."
HOMEPAGE = "https://gpiozero.readthedocs.io/"
AUTHOR = "Ben Nuttall <ben@bennuttall.com>"
LICENSE = "BSD-3-Clause"
LIC_FILES_CHKSUM = "file://LICENSE.rst;md5=f7edfe7aeac02cb6c394726db07eb41c"

SRC_URI[sha256sum] = "745feab6df463ac2e9de10c67e2dd9f396e668ba4e281e92381d6c460100a8f7"

inherit pypi python_setuptools_build_meta

RDEPENDS:${PN} += " \
    python3-colorzero \
"

