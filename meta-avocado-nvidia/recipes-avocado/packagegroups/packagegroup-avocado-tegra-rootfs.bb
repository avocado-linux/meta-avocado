DESCRIPTION = "Packagegroup for inclusion in all Avocado tegra images"
LICENSE = "Apache-2.0"

do_image[deptask] = "do_image_complete"
DEPENDS += "tegra-initrd-flash-initramfs"

inherit features_check

IMAGE_FEATURES += "splash hwcodecs"
REQUIRED_DISTRO_FEATURES = "opengl virtualization"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

# avocado-tegra-esp-generator is here rather than beside setup-nv-boot-control
# because it corrects that package's ESP mount and has to be present wherever
# the mount can be enabled, including images that pull the redundant-boot chain
# in through the BSP extension rather than through a packagegroup.
RDEPENDS:${PN} = " \
  tegra-firmware-tegra234 \
  avocado-tegra-esp-generator \
"

# nvbootctrl is the slot tool for every Jetson OS update: the stone manifest's
# slot_detection, activate and rollback actions all call it. It used to come
# only from the board's BSP extension, but rollback runs at boot before
# extensions merge, so it failed with "Failed to run slot action command: No
# such file or directory" and left the board on the failed slot.
RDEPENDS:${PN} += "tegra-redundant-boot-base"
