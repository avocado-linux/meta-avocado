DESCRIPTION = "Packagegroup for inclusion in all Avocado NXP i.MX rootfs images"
LICENSE = "Apache-2.0"

do_image[deptask] = "do_image_complete"

inherit features_check

IMAGE_FEATURES += "splash hwcodecs"
REQUIRED_DISTRO_FEATURES = ""

inherit packagegroup nospdx

# mmc-utils: `mmc extcsd read` / `mmc bootpart enable` are how a bootloader
# update targets the inactive eMMC boot0/boot1 hardware partition and flips
# PARTITION_CONFIG only after read-back verifies. Useful for field eMMC
# diagnostics regardless.
# systemd-serial-console-preset: every i.MX board here has a serial console
# only, so OE-core's `enable getty@.service` preset can only ever produce a
# failed getty@getty.service and a `degraded` system (seen on imx95-frdm and
# imx8mp-evk). Same fix nvidia/qcom carry per-vendor; this is the shared one.
RDEPENDS:${PN} = " \
  avocado-uboot-env \
  mmc-utils \
  systemd-serial-console-preset \
"

# SDMA RAM firmware (sdma-imx7d.bin) for the i.MX SDMAv3 controller (audio/SAI,
# UART, SPI DMA). On the NXP BSP it lives in firmware-imx (IMX_USE_LINUX_FIRMWARE_SDMA=0);
# the FSLC name linux-firmware-imx-sdma-imx7d does not exist there. Scope to the
# i.MX8MP NXP-BSP boards (imx8mp-evk / compulab / variscite) where firmware-imx
# provides it and the BSP extensions reference it; imx9/FRDM don't build this
# package, so an unconditional dep breaks their rootfs ("nothing provides
# firmware-imx-sdma-imx7d"). PACKAGE_ARCH=MACHINE_ARCH so the :mx8mp-nxp-bsp
# override resolves per-board (this packagegroup is otherwise noarch/shared).
PACKAGE_ARCH = "${MACHINE_ARCH}"
RDEPENDS:${PN}:append:mx8mp-nxp-bsp = " firmware-imx-sdma-imx7d"
