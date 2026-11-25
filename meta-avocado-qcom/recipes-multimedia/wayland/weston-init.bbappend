# The qcom weston.ini replaces weston-init's. It used to be installed by a
# weston bbappend, so weston and weston-init both owned
# /etc/xdg/weston/weston.ini with different contents, and installing weston
# (which RRECOMMENDS weston-init) failed dnf's transaction test.
FILESEXTRAPATHS:prepend := "${THISDIR}/files:"
SRC_URI:append = " file://weston.ini"

do_install:append () {
        install -m 0644 ${UNPACKDIR}/weston.ini -D ${D}${sysconfdir}/xdg/weston/weston.ini
}
