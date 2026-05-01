# SolidRun's TF-A v2.10.5/rzv2n_1.2.0 has two timing races on rzv2n-sr-som
# that are masked at LOG_LEVEL=50 by ~4-10 ms of incidental UART traffic at
# 115200 baud. The release-default LOG_LEVEL=20 hits both, with no visible
# error before each hang.
#
# Patch 1 — BL2 xspi_setup race:
#   xspi_setup() returns before the SPI NOR has settled into memory-mapped
#   read mode, so BL2's first XIP read of the FIP TOC at
#   RZV2N_SPIROM_FIP_BASE returns zeros. fip_file_open() treats TOC entry 0's
#   all-zero UUID as the null terminator and returns -ENOENT for BL31,
#   producing 'BL2: Failed to load image id 3 (-2)'. Fixed by 10 ms mdelay()
#   at the end of xspi_setup(). xspi.c is BL2-only.
#
# Patch 2 — BL31 bl31_platform_setup race:
#   The upstream tzc400 driver has no barriers/polls/delays between
#   disable_filters / configure / enable_filters. plat_tzc_sram_setup
#   configures two TZC instances back-to-back. At LOG_LEVEL=50, four INFO
#   prints inside plat_security_setup provide ~10 ms of settling time;
#   without them BL31 hangs immediately after its banner. Fixed by 10 ms
#   mdelay() at the start of bl31_platform_setup().
#
# Both should be reported upstream to SolidRun and Renesas.

FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI:append:rzv2n-sr-som = " \
    file://0001-rzv2n-xspi_setup-settle-SPI-flash-before-memory-map-.patch \
    file://0001-rzv2n-bl31_platform_setup-settle-SoC-fabric-before-T.patch \
"
