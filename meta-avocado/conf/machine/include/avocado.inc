AVOCADO_IMAGE_ROOTFS_TYPE ?= "squashfs"
AVOCADO_IMAGE_INITRAMFS_TYPE ?= "cpio.zst"
AVOCADO_IMAGE_VAR_TYPE ?= "btrfs"

MACHINEOVERRIDES =. "${@':'.join(['stone-' + opt for opt in d.getVar('STONE_PROVISIONING').split()])}:"
