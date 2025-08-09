inherit cargo cargo-update-recipe-crates

SRCBRANCH = "main"
SRCREV = "bcc8ceccc8d4a31081bdf799a298415458080041"
SRC_URI = "git://git@github.com/avocado-linux/mkfat.git;protocol=https;nobranch=1;branch=${SRCBRANCH}"

SRC_URI[sha256sum] = "3ebfa61108b7f31db116a647c21a547a15210bc005c16c04598f9e2b9153f3d1"

require ${BPN}-crates.inc

S = "${WORKDIR}/git"

CARGO_SRC_DIR = ""

LIC_FILES_CHKSUM = " \
    file://LICENSE;md5=fc7337d17cbe7b46e72ffd0502895ded \
"

SUMMARY = "A CLI for making fat filesystems from a JSON config."
HOMEPAGE = "https://github.com/avocado-linux/mkfat"
LICENSE = "Apache-2.0"

BBCLASSEXTEND = "native nativesdk"
