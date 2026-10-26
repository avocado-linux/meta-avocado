DESCRIPTION = "Packagegroup for inclusion in all Avocado Rockchip rootfs images"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"

inherit packagegroup

# avocado-uboot-env: boards with an A/B U-Boot environment (BOOTVARS =
# "ubootenv") need fw_env.config to name the disk they booted from.
RDEPENDS:${PN} = ""
RDEPENDS:${PN}:append:bootvars-ubootenv = " avocado-uboot-env"

# systemd-serial-console-preset: the R5S has no display output, so OE-core's
# getty@.service preset only ever yields a failed getty@getty.service and a
# degraded system.
RDEPENDS:${PN}:append:nanopi-r5s = " systemd-serial-console-preset"
