DESCRIPTION = "DLPack: Open In Memory Tensor Structure"
HOMEPAGE = "https://github.com/dmlc/dlpack"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://LICENSE;md5=f62d4e85ba68a1574b74d97ab8dea9ab"

SRC_URI = " \
    git://github.com/dmlc/dlpack.git;protocol=https;branch=main;tag=v${PV} \
    file://0001-update-dlpack-project-version.patch \
"
SRCREV = "93c8f2a3c774b84af6f652b1992c48164fae60fc"

inherit cmake

ALLOW_EMPTY:${PN} = "1"
