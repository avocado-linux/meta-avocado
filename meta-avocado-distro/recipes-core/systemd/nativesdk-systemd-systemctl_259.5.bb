SUMMARY = "Systemctl executable from systemd"

require recipes-core/systemd/systemd.inc

DEPENDS = "gperf-native libcap libxcrypt util-linux python3-jinja2-native"

inherit pkgconfig meson nativesdk

MESON_TARGET = "systemctl:executable"
MESON_INSTALL_TAGS = "systemctl"
EXTRA_OEMESON:append = " -Dlink-systemctl-shared=false"

# Systemctl is supposed to operate on target, but the target sysroot is not
# determined at run-time, but rather set during configure
# More details are here https://github.com/systemd/systemd/issues/35897#issuecomment-2665405887
EXTRA_OEMESON:append = " --sysconfdir ${SDKPATHNATIVE}${sysconfdir_nativesdk}"

