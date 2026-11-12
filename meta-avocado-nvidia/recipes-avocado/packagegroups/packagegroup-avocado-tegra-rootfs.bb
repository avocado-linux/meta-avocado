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

# The firmware set meta-tegra defines for this machine's SoC (its FWDEPS: the
# SoC's own package plus the vic, shared and xusb ones). Name the umbrella,
# not a subpackage: tegra-firmware-tegra234 gave Thor (tegra264) no GPU
# firmware, and the SoC package alone misses what upstream splits out of it
# (tegra-firmware-shared carries the NVJPG firmware).
RDEPENDS:${PN} = "tegra-firmware"
