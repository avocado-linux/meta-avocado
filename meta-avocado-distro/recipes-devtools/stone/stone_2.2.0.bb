inherit cargo cargo-update-recipe-crates

SRCBRANCH = "main"
SRCREV = "b58a6411b8e416b06cc2348f98acbb6fc0333c86"
SRC_URI = "git://git@github.com/avocado-linux/stone.git;protocol=https;nobranch=1;branch=${SRCBRANCH}"

require ${BPN}-crates.inc


CARGO_SRC_DIR = ""

LIC_FILES_CHKSUM = " \
    file://LICENSE;md5=86d3f3a95c324c9479bd8986968f4327 \
"

SUMMARY = "A CLI for managing Avocado stones."
HOMEPAGE = "https://github.com/avocado-linux/stone"
LICENSE = "Apache-2.0"

include stone-${PV}.inc
include stone.inc

BBCLASSEXTEND = "native nativesdk"
