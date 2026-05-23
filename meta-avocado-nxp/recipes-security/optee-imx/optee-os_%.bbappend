# See meta-avocado-nxp/recipes-multimedia/gstreamer/gstreamer1.0_%.bbappend
# for rationale.
PACKAGE_ARCH = "${MACHINE_ARCH}"

# imx95 15x15 FRDM board requires OP-TEE from the lf-6.18.2 branch which
# includes fixes for ELE/MU drivers and SOC ID corrections for B0 silicon.
SRCBRANCH:avocado-imx95-frdm = "lf-6.18.2_1.0.0"
SRCREV:avocado-imx95-frdm = "e7ed997213779e3d1b7417461c5b4847d3230db9"

# The clang sysroot patch was written against lf-6.6.36 and does not apply
# to lf-6.18.2 (mk/clang.mk was restructured).  The build uses GCC so the
# patch is not needed.
SRC_URI:remove:avocado-imx95-frdm = "file://0007-allow-setting-sysroot-for-clang.patch"
