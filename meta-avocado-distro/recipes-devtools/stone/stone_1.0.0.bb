inherit cargo cargo-update-recipe-crates

SRCBRANCH = "main"
SRCREV = "4967fb8161bcc1a4264d3563a078af46140213ee"
SRC_URI = "git://git@github.com/avocado-linux/stone.git;protocol=https;nobranch=1;branch=${SRCBRANCH}"

SRC_URI[sha256sum] = "3ebfa61108b7f31db116a647c21a547a15210bc005c16c04598f9e2b9153f3d1"

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

BBCLASSEXTEND = "nativesdk"
