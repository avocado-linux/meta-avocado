AVOCADO_IMAGE_ROOTFS_TYPE ?= "erofs-lz4"
AVOCADO_IMAGE_INITRAMFS_TYPE ?= "cpio.zst"
AVOCADO_IMAGE_VAR_TYPE ?= "btrfs"

STONE_PROVISIONING ?= ""
MACHINEOVERRIDES =. "${@':'.join(['stone-' + opt for opt in d.getVar('STONE_PROVISIONING').split()]) + ':' if d.getVar('STONE_PROVISIONING') and d.getVar('STONE_PROVISIONING').strip() else ''}"
