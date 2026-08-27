SUMMARY = "Fan management for RUBIK Pi 3"
DESCRIPTION = "Userspace fan controller for the RUBIK Pi 3. When SoC temperature \
crosses configured trip points, drives the on-board PWM fan via /sys/class/pwm. \
Prebuilt binary distribution; ships its own systemd service and config."
HOMEPAGE = "https://github.com/rubikpi-ai/rubikpi3_thermal"
LICENSE = "CLOSED"

# Source: https://github.com/rubikpi-ai/meta-rubikpi-bsp @ 227631ce94bb
# That layer used meta-qcom-hwe's qprebuilt.bbclass to unpack the tarball's
# sysroot-shaped tree into ${D}; the HWE layer is gone from this build, so do
# the same in a plain do_install (the tree is ./usr, ./etc plus a __LIC__ dir).
inherit pkgconfig
S = "${UNPACKDIR}"

DEPENDS += "libnl"
RDEPENDS:${PN} += "glibc"

SRC_URI = "https://raw.githubusercontent.com/rubikpi-ai/prebuilt/HLOS-BINs/rubikpi3-thermal_1.1.0.tar.gz;downloadfilename=rubikpi3-thermal_1.1.0.tar.gz"
SRC_URI[sha256sum] = "510af8ab75910d1e4953011fcab3dd6a35ec1d9ad221c33fa8af1eb6d41b449e"

# The upstream prebuilt tarball drops the executable at
# /etc/rubikpi/rubikpi-thermal and points the .service ExecStart at it. That
# works on Thundercomm's distro because /etc is a regular writable+exec
# filesystem there. On avocado, /etc is a confext overlay mounted noexec
# (config-files only); exec'ing from /etc fails with EACCES even though the
# binary's mode is 0755. Relocate the binary to /usr/bin/ (which lives on the
# /usr sysext overlay — exec'able) and patch the .service unit to match.
#
do_configure[noexec] = "1"
do_compile[noexec] = "1"
do_install() {
    install -d ${D}
    cp -a ${S}/usr ${S}/etc ${D}/
    install -d ${D}${bindir}
    if [ -f ${D}${sysconfdir}/rubikpi/rubikpi-thermal ]; then
        mv ${D}${sysconfdir}/rubikpi/rubikpi-thermal ${D}${bindir}/rubikpi-thermal
        # The prebuilt tar only had the binary under /etc/rubikpi/. After we
        # move it out, the /etc/rubikpi/ dir and (via rmdir) the parent /etc/
        # are empty; drop them so QA's installed-vs-shipped check doesn't
        # fail on the empty /etc not being in FILES.
        rmdir --ignore-fail-on-non-empty ${D}${sysconfdir}/rubikpi 2>/dev/null || true
        rmdir --ignore-fail-on-non-empty ${D}${sysconfdir}        2>/dev/null || true
    fi
    if [ -f ${D}${systemd_system_unitdir}/rubikpi-thermal.service ]; then
        sed -i 's|/etc/rubikpi/rubikpi-thermal|${bindir}/rubikpi-thermal|g' \
            ${D}${systemd_system_unitdir}/rubikpi-thermal.service
    fi
}

FILES:${PN} = " \
    ${bindir}/rubikpi-thermal \
    /usr/lib/* \
    /usr/include/* \
    /usr/lib/systemd/system/* \
    /usr/lib/systemd/system/multi-user.target.wants/* \
"

FILES:${PN}-dev = ""

INSANE_SKIP = "1"
INSANE_SKIP:${PN} = "already-stripped"
INSANE_SKIP:${PN} += "dev-so"
INSANE_SKIP:${PN} += "file-rdeps"

# Note: SYSTEMD_AUTO_ENABLE is intentionally NOT set here. This package only
# ever lands on a device via the BSP extension, and the extension layer
# enables services via its own `enable_services:` mechanism in
# bsp/<machine>/avocado.yaml — applied after the extension is merged. Setting
# SYSTEMD_AUTO_ENABLE in the recipe would also have no effect: avocado's
# system-preset 99-default.preset has `disable *` (opt-in policy), and the
# extension is read-only erofs so installtime symlinks in /etc would be
# obscured by the confext overlay anyway.
SYSTEMD_SERVICE:${PN} = "rubikpi-thermal.service"
