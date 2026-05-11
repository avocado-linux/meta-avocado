SUMMARY = "Rockchip USB flashing tool"
DESCRIPTION = "Host-side tool that talks the rockusb protocol over USB to \
program Rockchip SoCs (RK3399, RK356x, RK3588, ...) when the target is in \
MaskROM or Loader mode. Used by avocado-os's eMMC and NVMe provisioning \
profiles in the SDK; the target build also lets an avocado-os device \
provision another rockchip target over its USB host port."
HOMEPAGE = "https://github.com/rockchip-linux/rkdeveloptool"
LICENSE = "GPL-2.0-only"
LIC_FILES_CHKSUM = "file://license.txt;md5=ea9445d9cc03d508cf6bb769d15a54ef"

SRC_URI = "git://github.com/rockchip-linux/rkdeveloptool.git;branch=master;protocol=https"
SRCREV = "304f073752fd25c854e1bcf05d8e7f925b1f4e14"

S = "${WORKDIR}/git"

DEPENDS = "libusb1"

inherit autotools pkgconfig

# Upstream Makefile.am ships -Werror; cross-compile builds occasionally
# surface a benign -Wstringop-overflow or -Wdeprecated-declarations that
# would otherwise fail the build. Drop -Werror for our builds.
CXXFLAGS:append = " -Wno-error"

# Install the udev rule for the target variant only so that an avocado-os
# device acting as a host can reach rkusb endpoints without root. SDK and
# native builds don't need it.
do_install:append:class-target() {
    install -d ${D}${nonarch_base_libdir}/udev/rules.d
    install -m 0644 ${S}/99-rk-rockusb.rules \
        ${D}${nonarch_base_libdir}/udev/rules.d/99-rk-rockusb.rules
}

FILES:${PN} += "${nonarch_base_libdir}/udev/rules.d/99-rk-rockusb.rules"

BBCLASSEXTEND = "native nativesdk"
