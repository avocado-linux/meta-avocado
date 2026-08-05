DESCRIPTION = "Packagegroup for extra packages in Avocado NXP i.MX SDKs"
LICENSE = "Apache-2.0"

# MACHINE_ARCH so the per-SoC :append overrides below are honored (a default
# allarch packagegroup would drop the machine overrides and the gating would
# silently never match). Mirrors packagegroup-avocado-imx-ml.
PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup

RDEPENDS:${PN} = " \
  nativesdk-uuu \
"

# NPU model compiler -> SDK feed. Vela compiles models for the Arm Ethos-U
# offline, on the SDK host, so it is nativesdk and belongs in the SDK feed (the
# Ethos-U runtime delegate is in packagegroup-avocado-imx-ml). Gated on
# mx93-nxp-bsp: only i.MX93 (Ethos-U) SDKs ship it. i.MX8MP uses the Vivante VX
# runtime delegate and needs no offline compiler, so it is intentionally omitted.
RDEPENDS:${PN}:append:mx93-nxp-bsp = " nativesdk-ethos-u-vela"
