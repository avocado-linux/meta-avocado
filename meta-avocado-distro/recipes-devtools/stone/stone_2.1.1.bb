inherit cargo cargo-update-recipe-crates

SRCBRANCH = "rel/2.1.1"
SRCREV = "7c46ad425eec184fcd5db894b76b8213e154400e"
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
