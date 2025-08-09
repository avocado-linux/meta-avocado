UBOOT_ENV_SIZE = "0x20000"

IMAGE_BOOT_FILES:append = " avocado-image-initramfs-${MACHINE}.cpio.zst;avocado-initramfs.cpio.zst"

RPI_USE_U_BOOT = "1"

CMDLINE_ROOT_PARTITION = "/dev/mmcblk0p2"
CMDLINE_ROOT_FSTYPE = "rootfstype=squashfs"

AVOCADO_VAR_PART_DEV = "/dev/mmcblk0p3"

DEPENDS:append:pn-mesa = " libxshmfence"
