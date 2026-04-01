PREFERRED_VERSION_linux-raspberrypi ?= "6.12.%"

UBOOT_ENV_SIZE = "0x20000"

IMAGE_BOOT_FILES:append = " avocado-image-initramfs-${MACHINE}.cpio.zst;avocado-initramfs.cpio.zst"

RPI_USE_U_BOOT = "1"
ENABLE_DWC2_HOST = "1"

# Partition layout: p1=boot(FAT), p2=uboot-env(FAT), p3=rootfs, p4=var
CMDLINE_ROOT_PARTITION = "/dev/mmcblk0p3"
CMDLINE_ROOT_FSTYPE = "rootfstype=erofs"
CMDLINE:append = " audit=0"

AVOCADO_VAR_PART_DEV = "/dev/mmcblk0p4"

DEPENDS:append:pn-mesa = " libxshmfence"
