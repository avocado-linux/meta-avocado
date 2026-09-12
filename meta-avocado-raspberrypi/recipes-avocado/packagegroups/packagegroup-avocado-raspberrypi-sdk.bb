DESCRIPTION = "Packagegroup for inclusion in Avocado reTerminal SDKs"
LICENSE = "Apache-2.0"

# No SPDX: do_create_package_spdx resolves every RDEPENDS' packages-staging
# document through SSTATE_ARCHS, which under allarch (SDK_ARCH = "none") can
# never name this group's SDK-arch deps. Metadata only - nothing to record.
inherit packagegroup avocado-nospdx

RDEPENDS:${PN} = " \
  nativesdk-rpi-usbboot \
"
