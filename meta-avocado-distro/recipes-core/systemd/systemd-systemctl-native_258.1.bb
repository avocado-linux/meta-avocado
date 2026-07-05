FILESEXTRAPATHS:prepend := "${THISDIR}/systemd:"

SUMMARY = "Systemctl executable from systemd"

require systemd.inc

DEPENDS = "gperf-native libcap-native util-linux-native python3-jinja2-native"

inherit pkgconfig meson_tags native

MESON_TARGET = "systemctl:executable"
MESON_INSTALL_TAGS = "systemctl"
EXTRA_OEMESON += "-Dlink-systemctl-shared=false"

# systemd's meson pam option defaults to 'auto', so on a host that has libpam the
# probe enables PAM and libsystemd-shared compiles pam-util.c, which needs
# security/pam_ext.h and fails when the recipe sysroot has no pam headers. This
# native helper (systemctl:executable only) never uses PAM, and a dependency
# cannot supply the header: libpam gates on ANY_OF_DISTRO_FEATURES "pam systemd"
# and native builds use DISTRO_FEATURES_NATIVE (no pam), so there is no
# libpam-native provider. Disable the probe; the target systemd keeps PAM.
EXTRA_OEMESON += "-Dpam=disabled"
EXTRA_OEMESON += "-Dsysvinit-path= -Dsysvrcnd-path="

# Systemctl is supposed to operate on target, but the target sysroot is not
# determined at run-time, but rather set during configure
# More details are here https://github.com/systemd/systemd/issues/35897#issuecomment-2665405887
EXTRA_OEMESON += "--sysconfdir ${sysconfdir_native}"

do_install:append() {
	# Install systemd-sysv-install in /usr/bin rather than /usr/lib/systemd
	# (where it is normally installed) so systemctl can find it in $PATH.
	# It is expected that the use of systemd-sysv-install will be removed
	# with version 259 of systemd and then this, and everything that was
	# added along with it, should be reverted.
	install -Dm 0755 ${S}/src/systemctl/systemd-sysv-install.SKELETON ${D}${bindir}/systemd-sysv-install
}
