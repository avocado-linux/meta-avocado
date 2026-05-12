# meta-imx ships .imx-versioned variants of upstream gstreamer/libdrm/weston/
# opencv/optee/etc. that leave PACKAGE_ARCH at TUNE_PKGARCH (e.g. cortexa55),
# so their RPMs land in the shared feed and shadow upstream on non-iMX boards
# that share TUNE_PKGARCH. Some are partially scoped to MACHINE_SOCARCH
# upstream, but that still co-mingles RPMs across iMX boards on the same SoC
# (e.g. imx8mp-evk vs imx8mp-frdm), as seen with optee-os/optee-test. Pin to
# MACHINE_ARCH so each iMX board gets its own slice of the feed.
PACKAGE_ARCH = "${MACHINE_ARCH}"
