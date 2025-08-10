inherit cargo cargo-update-recipe-crates

SRCBRANCH = "main"
SRCREV = "4639417438c3a0ddb8d89371caf922cf4f043e70"
SRC_URI = "git://git@github.com/avocado-linux/stone.git;protocol=https;nobranch=1;branch=${SRCBRANCH}"

require ${BPN}-crates.inc

S = "${WORKDIR}/git"

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
