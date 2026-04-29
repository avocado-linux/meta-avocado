SUMMARY = "Simple Signed Certificate Generator"
DESCRIPTION = "SSCG makes it easy to generate usable, signed x509 certificates \
without having to learn complex openssl/certtool/certutil invocation."
HOMEPAGE = "https://github.com/sgallagher/sscg"
SECTION = "security"
LICENSE = "GPL-3.0-or-later"
LIC_FILES_CHKSUM = "file://COPYING;md5=06b2e25ecfb8731bfa17b888103be94a"

FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI = "git://github.com/sgallagher/sscg.git;branch=main;protocol=https \
           file://0001-Remove-man-page-creation.patch \
"
SRCREV = "9708ebc93d829c705b8204769d0ffeb9671b8397"


inherit meson pkgconfig

DEPENDS = "openssl popt libtalloc"