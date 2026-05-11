# optee-os is typically MACHINE_ARCH already from optee-os.bbclass, but the
# .imx variant doesn't restate it; pin to per-SoC for parity with the rest
# of the meta-avocado-nxp .imx-scope tightening. See ../../recipes-graphics
# /drm/libdrm_%.bbappend for the full cross-pollution rationale.
PACKAGE_ARCH = "${MACHINE_SOCARCH}"
