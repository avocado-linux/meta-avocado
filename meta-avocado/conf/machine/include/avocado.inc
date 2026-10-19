AVOCADO_IMAGE_ROOTFS_TYPE ?= "erofs-lz4"
AVOCADO_IMAGE_INITRAMFS_TYPE ?= "cpio.zst"
AVOCADO_IMAGE_VAR_TYPE ?= "btrfs"

# erofs block size for the rootfs and extension images, exported to the SDK
# (avocado-sdk-target) for avocado-cli's mkfs.erofs. Empty keeps the mkfs
# default (4 KiB). A machine whose kernel uses larger pages sets it to the page
# size: older kernels cannot read compressed inodes in smaller blocks.
AVOCADO_EROFS_BLOCK_SIZE ?= ""

# Boot method for this machine: "uboot" (U-Boot + TF-A, fwup disk assembly) or
# "uefi" (systemd-boot + GPT). Boot-artifact deps in the stone / img-bootfiles /
# SDK bbappends gate on it. Defaults to U-Boot (the common case for the ARM
# boards); x86 machines set uefi.
AVOCADO_BOOTLOADER ?= "uboot"

STONE_PROVISIONING ?= ""
MACHINEOVERRIDES =. "${@':'.join(['stone-' + opt for opt in d.getVar('STONE_PROVISIONING').split()]) + ':' if d.getVar('STONE_PROVISIONING') and d.getVar('STONE_PROVISIONING').strip() else ''}"
