# meta-imx's .imx-versioned variant defaults PACKAGE_ARCH to TUNE_PKGARCH
# (e.g. cortexa55), so its RPMs leak into the shared feed and shadow upstream
# gstreamer on non-iMX boards that share the same TUNE_PKGARCH. Pin to the
# SoC arch so iMX gstreamer only lands in the per-SoC dir.
PACKAGE_ARCH = "${MACHINE_SOCARCH}"
