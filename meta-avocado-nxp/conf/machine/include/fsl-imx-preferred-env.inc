# Copied from meta-imx/meta-imx-sdk/conf/distro/include/fsl-imx-preferred-env.inc
PREFERRED_PROVIDER_virtual/bootloader:use-nxp-bsp = "u-boot-imx"
PREFERRED_PROVIDER_virtual/kernel:use-nxp-bsp = "linux-imx"
PREFERRED_PROVIDER_linux-imx-mfgtool = "linux-imx-mfgtool"

PREFERRED_VERSION_gstreamer1.0              = "1.24.0.imx"
PREFERRED_VERSION_gstreamer1.0-plugins-base = "1.24.0.imx"
PREFERRED_VERSION_gstreamer1.0-plugins-good = "1.24.0.imx"
PREFERRED_VERSION_gstreamer1.0-plugins-bad  = "1.24.0.imx"
PREFERRED_VERSION_gstreamer1.0-plugins-ugly = "1.24.0.imx"
PREFERRED_VERSION_gstreamer1.0-libav        = "1.24.0.imx"
PREFERRED_VERSION_gstreamer1.0-rtsp-server  = "1.24.0.imx"

PREFERRED_VERSION_gstreamer1.0:mx8-nxp-bsp              = "1.24.0.imx"
PREFERRED_VERSION_gstreamer1.0-plugins-base:mx8-nxp-bsp = "1.24.0.imx"
PREFERRED_VERSION_gstreamer1.0-plugins-good:mx8-nxp-bsp = "1.24.0.imx"
PREFERRED_VERSION_gstreamer1.0-plugins-bad:mx8-nxp-bsp  = "1.24.0.imx"
PREFERRED_VERSION_gstreamer1.0-plugins-ugly:mx8-nxp-bsp = "1.24.0.imx"
PREFERRED_VERSION_gstreamer1.0-libav:mx8-nxp-bsp        = "1.24.0.imx"
PREFERRED_VERSION_gstreamer1.0-rtsp-server:mx8-nxp-bsp  = "1.24.0.imx"

PREFERRED_VERSION_gstreamer1.0:mx9-nxp-bsp              = "1.24.0.imx"
PREFERRED_VERSION_gstreamer1.0-plugins-base:mx9-nxp-bsp = "1.24.0.imx"
PREFERRED_VERSION_gstreamer1.0-plugins-good:mx9-nxp-bsp = "1.24.0.imx"
PREFERRED_VERSION_gstreamer1.0-plugins-bad:mx9-nxp-bsp  = "1.24.0.imx"
PREFERRED_VERSION_gstreamer1.0-plugins-ugly:mx9-nxp-bsp = "1.24.0.imx"
PREFERRED_VERSION_gstreamer1.0-libav:mx9-nxp-bsp        = "1.24.0.imx"
PREFERRED_VERSION_gstreamer1.0-rtsp-server:mx9-nxp-bsp  = "1.24.0.imx"

# imx93-frdm carries no meta-avocado gstreamer pin: it is on the wrynose
# 6.18.20-2.0.0 meta-imx, which ships only 1.28.1.imx recipes. The 1.24.0.imx
# above matches nothing there, so bitbake warns once and falls back - the pin
# reads as authoritative while deciding nothing, and the next person to open
# this file would believe 1.24.0.imx is what ships. Clearing it lets
# meta-imx-bsp/conf/machine/include/imx-base-extend.inc:69 state the version
# for its own release, which keeps stating it correctly across BSP bumps.
#
# Scoped to the machine because imx91-frdm and imx95-frdm still take
# nxp-frdm.yml's 6.6.36 meta-imx, where 1.24.0.imx does exist and the pin above
# is live.
PREFERRED_VERSION_gstreamer1.0:avocado-imx93-frdm              = ""
PREFERRED_VERSION_gstreamer1.0-plugins-base:avocado-imx93-frdm = ""
PREFERRED_VERSION_gstreamer1.0-plugins-good:avocado-imx93-frdm = ""
PREFERRED_VERSION_gstreamer1.0-plugins-bad:avocado-imx93-frdm  = ""
PREFERRED_VERSION_gstreamer1.0-plugins-ugly:avocado-imx93-frdm = ""
PREFERRED_VERSION_gstreamer1.0-libav:avocado-imx93-frdm        = ""
PREFERRED_VERSION_gstreamer1.0-rtsp-server:avocado-imx93-frdm  = ""

PREFERRED_VERSION_xen-tools = "4.18.imx+stable"
PREFERRED_VERSION_xen = "4.18.imx+stable"

QEMUVERSION              = "8.2.2"
QEMUVERSION:mx95-nxp-bsp = "8.2.2.imx"
QEMUVERSION:mx93-nxp-bsp = "8.2.2.imx"
QEMUVERSION:mx91-nxp-bsp = "8.2.2.imx"

# imx93-frdm's wrynose meta-imx ships qemu 10.2.5.imx, not 8.2.2.imx: the
# mx93-nxp-bsp pin above matches nothing there, decides nothing, and reads as
# authoritative to the next reader. Clearing it lets
# meta-imx-bsp/conf/machine/include/imx-base-extend.inc:112-113's own weak
# default state the version for its release, same as the gstreamer pins
# above. Scoped to the machine, not mx93-nxp-bsp, because imx91-frdm and
# imx95-frdm still take nxp-frdm.yml's 6.6.36 meta-imx, where 8.2.2.imx is
# live.
QEMUVERSION:avocado-imx93-frdm = ""

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

# meta-avocado-nxp's own nnstreamer append drops the tvm PACKAGECONFIG that
# NXP's nnstreamer turns on for mx8mp-nxp-bsp only, and is a no-op everywhere
# else tvm isn't enabled - which is every fsl-imx-preferred-env.inc machine.
# At 6.18 meta-imx-ml (the only other source of an nnstreamer recipe) ships
# nnstreamer as append-only, with no base recipe in this layer set to append
# to; meta-openembedded has never provided one on either series. Masking here
# rather than per-machine covers every BSP this include reaches, present and
# future.
BBMASK += "meta-avocado/meta-avocado-nxp/recipes-nnstreamer/nnstreamer/nnstreamer_%.bbappend"

# Use systemd as default init manager
POKY_INIT_MANAGER = "systemd"

# Use virtual-runc as a default container runtime
# runtime: runc, crun, runv, runx
VIRTUAL-RUNTIME_container_runtime = "virtual-runc"
