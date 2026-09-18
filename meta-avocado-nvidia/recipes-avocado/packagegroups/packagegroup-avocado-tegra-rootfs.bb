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

# The A/B update path, which until now was reachable only by an image that also
# took packagegroup-avocado-tegra-extra. That group goes to PKG_EXTRA_INSTALL,
# which populates the feed rather than the image, so `swupdate` and `nvbootctrl`
# were installable and not installed. A stock Jetson image therefore shipped
# SWUpdate handlers it could not run: rootfs-pre.sh exits at its first check,
# `command -v nvbootctrl`.
#
# tegra-redundant-boot-base is the whole chain, not just the binary. It pulls
# setup-nv-boot-control-service, whose unit generates /etc/nv_boot_control.conf
# at boot, and that in turn pulls tegra-nv-boot-control-config for the template
# it renders and tegra-eeprom-tool-boardspec for the boardspec it reads. Naming
# only nvbootctrl would install a tool that fails on a missing config file.
#
# swupdate carries its own /etc/swupdate.cfg and /etc/hwrevision. The pre- and
# post-install handlers are not part of it: those are deployed into the .swu
# bundle, so the update carries them rather than the image.
RDEPENDS:${PN} = " \
  tegra-firmware-tegra234 \
  tegra-redundant-boot-base \
  swupdate \
"
