# Native iMX gstreamer plugins recipe; default PACKAGE_ARCH would still drop
# it into the shared TUNE_PKGARCH feed. See gstreamer1.0_%.bbappend.
PACKAGE_ARCH = "${MACHINE_SOCARCH}"
