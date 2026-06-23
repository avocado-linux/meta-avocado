DESCRIPTION = "Packagegroup for inclusion in all Avocado NXP i.MX rootfs images"
LICENSE = "Apache-2.0"

do_image[deptask] = "do_image_complete"

inherit features_check

IMAGE_FEATURES += "splash hwcodecs"
REQUIRED_DISTRO_FEATURES = ""

inherit packagegroup nospdx

RDEPENDS:${PN} = " \
  avocado-uboot-env \
  firmware-imx-sdma-imx7d \
"

# SoC-level SDMA RAM firmware (sdma-imx7d.bin), needed by every i.MX SDMAv3
# controller (audio/SAI, UART, SPI DMA). On the NXP BSP this lives in
# firmware-imx (IMX_USE_LINUX_FIRMWARE_SDMA=0); pulling it here builds the
# package into the feed and installs it on all i.MX rootfs (the FSLC name
# linux-firmware-imx-sdma-imx7d does not exist on the NXP BSP). noarch.
