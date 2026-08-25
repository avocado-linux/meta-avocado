# Copied from meta-imx/meta-imx-sdk/conf/distro/include/fsl-imx-preferred-env.inc
PREFERRED_PROVIDER_virtual/bootloader:use-nxp-bsp = "u-boot-imx"
PREFERRED_PROVIDER_virtual/kernel:use-nxp-bsp = "linux-imx"
PREFERRED_PROVIDER_linux-imx-mfgtool = "linux-imx-mfgtool"

# No gstreamer / qemu / xen version pins here: every NXP-BSP machine on this
# branch takes meta-imx wrynose-6.18.20-2.0.0, whose
# meta-imx-bsp/conf/machine/include/imx-base-extend.inc states the versions for
# its own release. (scarthgap pinned 1.24.0.imx / 8.2.2.imx / 4.18.imx here for
# the 6.6 releases; none of those versions exist at 6.18.20.)


# The only provider of gstreamer1.0-plugins-imx is meta-freescale's
# gstreamer1.0-plugins-imx_2.2.0.bb, which the BBMASK above masks wholesale on
# meta-freescale/recipes-multimedia/gstreamer. That pairing predates every
# fsl-imx-preferred-env.inc machine (7deb37dd, "Add support for NXP iMX FRDM
# boards"), so meta-avocado-nxp's own append below has been dangling on all of
# them since, and only started surfacing once the imx93 build got far enough
# to report it.
BBMASK += "meta-freescale/recipes-multimedia/gstreamer"
BBMASK += "meta-avocado/meta-avocado-nxp/recipes-multimedia/gstreamer/gstreamer1.0-plugins-imx_%.bbappend"
BBMASK += "meta-arm/meta-arm/recipes-kernel/linux/linux-yocto_5.15%.bbappend"

BBMASK += "meta-imx/meta-imx-bsp/recipes-kernel/cryptodev/cryptodev-linux_1.13.bbappend"
BBMASK += "meta-imx/meta-imx-bsp/recipes-graphics/xwayland/xwayland_23.1.1.imx.bbappend"

# Mask out the following recipe to prevent the same patches from being applied twice
BBMASK += "meta-imx/meta-imx-bsp/recipes-graphics/mesa/mesa_%.bbappend"


# Use systemd as default init manager
POKY_INIT_MANAGER = "systemd"

# Use virtual-runc as a default container runtime
# runtime: runc, crun, runv, runx
VIRTUAL-RUNTIME_container_runtime = "virtual-runc"
