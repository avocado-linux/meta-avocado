SUMMARY = "Host-side serial driver for Renesas Flash Writer (RZ/V2N SoM)"
DESCRIPTION = "Python tool that drives the on-target Flash Writer firmware over \
SCIF UART to program SPI NOR or eMMC boot partitions of Renesas RZ-family SoCs."
HOMEPAGE = "https://github.com/SolidRun/rzg2_flash_writer"
LICENSE = "BSD-3-Clause"
LIC_FILES_CHKSUM = "file://../LICENSE.md;md5=e4c8ad3b0ba7659157573c0d9d4bd496"

SRC_URI = "git://github.com/SolidRun/rzg2_flash_writer.git;branch=rz_v2n;protocol=https"
SRCREV = "e9e0ae0a5b194a2d68dc5413d29b15f190f2a350"

S = "${WORKDIR}/git/flash-tools"

inherit nativesdk

RDEPENDS:${PN} = " \
    nativesdk-python3-core \
    nativesdk-python3-pyserial \
    nativesdk-python3-tqdm \
"

do_compile[noexec] = "1"

do_install() {
    install -d ${D}${bindir}
    install -m 0755 ${S}/flash_writer_tool.py ${D}${bindir}/rz-flash-writer-tool
}
