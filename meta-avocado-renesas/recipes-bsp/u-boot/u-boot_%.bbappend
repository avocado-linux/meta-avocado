FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

SRC_URI:append = " \
  file://avocado.cfg \
  file://env-nowhere.cfg \
  file://fastboot.cfg \
"

# The RDK has no USB device/gadget port (USB3.2 are host-only, the Micro-B is a
# UART), so u-boot fastboot cannot run here. Drop the shared fastboot fragment on
# this machine: it is dead weight that also pushed u-boot-nodtb.bin past the
# board's 0x100000 size limit. (env-nowhere.cfg keeps a harmless `fastboot`
# fallback token in BOOTCOMMAND, but the board config header overrides
# BOOTCOMMAND anyway, so nothing references the removed command at runtime.)
SRC_URI:remove:rzv2h-rdk = "file://fastboot.cfg"

# The vendor rzv2h-dev.h hardcodes a CONFIG_BOOTCOMMAND that ext4loads the
# kernel + EVK dtb from a single ext4 rootfs and boots with booti - it cannot
# boot the Avocado layout (FAT boot partition with extlinux.conf + erofs rootfs
# by PARTUUID). Patch CONFIG_BOOTCOMMAND to sysboot the extlinux.conf instead.
# See the patch header; the bootcmd is build-verified only and must be
# confirmed at the u-boot prompt on hardware.
SRC_URI:append:rzv2h-rdk = " file://0001-rzv2h-dev-boot-avocado-extlinux.patch"
