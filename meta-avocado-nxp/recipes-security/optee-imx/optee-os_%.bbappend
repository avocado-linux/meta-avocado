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

# meta-arm's optee-os.inc names "linaro:op-tee op-tee:op-tee_os". The second pair
# is in no NVD record at all, and linaro:op-tee holds 2 of the 31 that exist -
# the other 29 are trustedfirmware:op-tee. So this recipe finds 2, both Patched,
# and reads like a scan that works. Same defect fixed for Jetson in ENG-2592.
CVE_PRODUCT = "trustedfirmware:op-tee linaro:op-tee"

# get_cpe_ids() strips only +git, so the .imx suffix would reach the published
# SPDX and VEX as a CPE version no NVD record uses. cve-check's range comparison
# parses the suffix fine, which is what hides this. Derived rather than a literal
# because the seven i.MX machines pin different meta-imx releases (4.2.0.imx on
# FRDM, 4.4.0.imx on EVK/CompuLab/Variscite) and the next vendor bump moves it
# again.
CVE_VERSION = "${@d.getVar('PV').split('.imx')[0]}"

# imx95-frdm is repointed at lf-6.18.2_1.0.0 above, which NXP ships as
# optee-os_4.8.0.imx.bb (vendor-meta-imx 8f1cbb7a21); the recipe selected here is
# still 4.2.0.imx, so PV describes neither the source built nor the CVE ranges to
# match against.
CVE_VERSION:avocado-imx95-frdm = "4.8.0"
