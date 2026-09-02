PREFERRED_VERSION_linux-raspberrypi ?= "6.12.%"

UBOOT_ENV_SIZE = "0x20000"

IMAGE_BOOT_FILES:append = " avocado-image-initramfs-${MACHINE}.cpio.zst;avocado-initramfs.cpio.zst"

RPI_USE_U_BOOT = "1"
ENABLE_DWC2_HOST = "1"

CMDLINE_ROOT_PARTITION = "/dev/mmcblk0p2"
CMDLINE_ROOT_FSTYPE = "rootfstype=erofs"
CMDLINE:append = " audit=0"

AVOCADO_VAR_PART_DEV = "/dev/mmcblk0p3"

DEPENDS:append:pn-mesa = " libxshmfence"

# RPI_USE_U_BOOT above puts u-boot on the device, and the AVOCADO_CVE_BOOT_CHAIN
# default already names it. These are the stages before it: the GPU firmware
# that loads everything, the EEPROM bootloader on Pi 4 and 5, and the ARM stub
# the kernel is entered from. rpi-u-boot-scr, rpi-config and rpi-cmdline are
# left out - a boot script and two text files have no CVE surface.
AVOCADO_CVE_BOOT_CHAIN:append = " rpi-bootfiles rpi-eeprom armstubs"
