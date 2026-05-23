# Pass the silicon revision to the OEI build system so the DDR OEI firmware
# is compiled for the correct silicon stepping (A0/B0/…).
# The meta-imx recipe does not include meta-freescale's imx-oei.inc which
# carries this argument, so we add it here.
EXTRA_OEMAKE:append:mx95-generic-bsp = " r=${IMX_SOC_REV}"

# Pin to a commit that renames the mx95lp4x-15 DDR timing file to the
# DDR-tool-generated name (MIMX95_LPDDR4X_EVK_15X15_4000MTS_FW2024.09_timing.c).
# The meta-imx recipe is pinned to 5fca9f47 which still carries the old name
# (XIMX95LPD4XCPU15_4000mbps_train_timing.c) and DDR training fails with it
# on the FRDM board.  LICENSE.txt is unchanged between the two commits.
SRCREV:mx95-generic-bsp = "fa9e9a29e8c8939cc360beafd01393ca393e439a"
