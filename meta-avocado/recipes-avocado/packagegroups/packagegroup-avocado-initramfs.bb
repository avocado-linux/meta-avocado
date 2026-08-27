DESCRIPTION = "Packagegroup for inclusion in Avocado initramfs image"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup nospdx
PACKAGES = "${PN}"

RDEPENDS:${PN} = "\
  ${@bb.utils.contains('AVOCADO_SECURITY_CAPABILITIES', 'encrypted-var', 'cryptsetup cryptsetup-var', '', d)} \
  systemd \
  systemd-extra-utils \
  os-release-initrd \
  avocado-security-capabilities \
  util-linux \
  util-linux-blkid \
  util-linux-lsblk \
  avocadoctl \
  avocado-users \
  ${@bb.utils.contains('DISTRO_FEATURES','zram','systemd-zram-generator','',d)} \
  ${@bb.utils.contains('MACHINE_FEATURES','optee-ftpm','optee-ftpm-init','',d)} \
  packagegroup-avocado-initramfs-modules \
"

RDEPENDS:${PN}:append:bootvars-ubootenv = " libubootenv-bin"

# A UEFI target boots systemd-boot out of a per-slot ESP, and stone hands both
# ESPs the same boot image, so the loader entry's root= cannot name the slot -
# only the LoaderDevicePartUUID the firmware set can. Gated on the boot method
# rather than on the machine because that is the property the generator needs:
# a U-Boot target reads its slot from a U-Boot variable and has no ESP to ask.
RDEPENDS:${PN} += "${@bb.utils.contains('AVOCADO_BOOTLOADER', 'uefi', 'avocado-slot-root-generator', '', d)}"
