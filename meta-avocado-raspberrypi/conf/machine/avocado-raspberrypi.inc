WKS_FILE ?= "avocado-raspberrypi.wks"

IMAGE_BOOT_FILES:append = " avocado-image-initramfs-${MACHINE}.cpio.zst;avocado-initramfs.cpio.zst"
IMAGE_BOOT_FILES:append = " devicetree/reTerminal.dtbo;overlays/reTerminal.dtbo"

RPI_USE_U_BOOT = "1"

CMDLINE_ROOT_PARTITION = "/dev/mmcblk0p2"
CMDLINE_ROOT_FSTYPE = "rootfstype=squashfs"
