DESCRIPTION = "Packagegroup for inclusion in all Avocado tegra images"
LICENSE = "Apache-2.0"

do_image[deptask] = "do_image_complete"
DEPENDS += "tegra-initrd-flash-initramfs"

inherit features_check

IMAGE_FEATURES += "splash hwcodecs"
REQUIRED_DISTRO_FEATURES = "opengl virtualization"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup nospdx
PACKAGES = "${PN}"

# The firmware set of this machine's SoC (tegra234: Orin, tegra264: Thor). A
# Thor rootfs with the Orin set has no GPU or display firmware: nvidia.ko's
# RmInitAdapter fails on nvidia/<version>/gsp_ga10x.bin, and EGL, CUDA and
# Argus with it.
RDEPENDS:${PN} = "tegra-firmware-${SOC_FAMILY}"
