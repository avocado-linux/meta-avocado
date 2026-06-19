DESCRIPTION = "IPP-over-USB printing support daemon"
HOMEPAGE = "https://github.com/OpenPrinting/ipp-usb"
LICENSE = "BSD-2-Clause"
LIC_FILES_CHKSUM = "file://src/${GO_IMPORT}/LICENSE;md5=35b61b5975388824d233d3f4ee283ad0"

GO_IMPORT = "github.com/OpenPrinting/ipp-usb"

SRC_URI = "git://github.com/OpenPrinting/ipp-usb.git;protocol=https;branch=master"
SRCREV = "1fb7787f2cdfd66236c0cc494e6c036b76a7b396"

inherit go-mod systemd

DEPENDS = "libusb1 avahi"

SYSTEMD_SERVICE:${PN} = "ipp-usb.service"

# Use vendored deps committed in the repo; no proxy or network needed
GOBUILDFLAGS:append = " -mod=vendor -tags nethttpomithttp2"

do_compile() {
    export TMPDIR="${GOTMPDIR}"
    mkdir -p ${B}/bin
    cd ${B}/src/${GO_IMPORT}
    ${GO} build ${GOBUILDFLAGS} -o ${B}/bin/ipp-usb .
}

do_install() {
    install -d ${D}${sbindir}
    install -m 0755 ${B}/bin/ipp-usb ${D}${sbindir}/ipp-usb

    install -d ${D}${sysconfdir}/ipp-usb
    install -m 0644 ${B}/src/${GO_IMPORT}/ipp-usb.conf ${D}${sysconfdir}/ipp-usb/

    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${B}/src/${GO_IMPORT}/systemd-udev/ipp-usb.service ${D}${systemd_system_unitdir}/

    install -d ${D}${base_libdir}/udev/rules.d
    install -m 0644 ${B}/src/${GO_IMPORT}/systemd-udev/71-ipp-usb.rules ${D}${base_libdir}/udev/rules.d/

    install -d ${D}${datadir}/ipp-usb/quirks
    install -m 0644 ${B}/src/${GO_IMPORT}/ipp-usb-quirks/* ${D}${datadir}/ipp-usb/quirks/
}

FILES:${PN} += " \
    ${sysconfdir}/ipp-usb/ \
    ${base_libdir}/udev/rules.d/ \
    ${datadir}/ipp-usb/ \
"

RDEPENDS:${PN} = "avahi-daemon"
