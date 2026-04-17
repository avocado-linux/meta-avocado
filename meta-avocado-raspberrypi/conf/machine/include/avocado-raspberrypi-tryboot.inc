# Tryboot targets: EEPROM loads kernel directly, no U-Boot second stage.
# Requires Pi 4/5 EEPROM firmware >= 2022-12-06 for tryboot support.
#
# Uses GPT partition table with PARTLABELs for storage-agnostic
# device identification (works across SD, eMMC, NVMe, SATA).
#
# Partition layout (GPT):
#   p1: boot-a    (FAT32, 128 MiB, PARTLABEL=boot-a)
#   p2: boot-b    (FAT32, 128 MiB, PARTLABEL=boot-b)
#   p3: rootfs-a  (erofs,  160 MiB, PARTLABEL=rootfs-a)
#   p4: rootfs-b  (erofs,  160 MiB, PARTLABEL=rootfs-b)
#   p5: uboot-env (FAT12,    1 MiB, PARTLABEL=uboot-env)
#   p6: var       (btrfs,  512 MiB, PARTLABEL=var, expandable)

RPI_USE_U_BOOT = "0"

# Rootfs: use PARTLABEL for storage-agnostic root device
CMDLINE_ROOT_PARTITION = "PARTLABEL=rootfs-a"

# Var partition: use the standard PARTUUID that matches the partition_uuid
# in the stone manifest. This overrides the base inc's /dev/mmcblk0p4.
AVOCADO_VAR_PART_DEV = "PARTUUID=4d21b016-b534-45c2-a9fb-5c16e091fd2d"

# Pull in the tryboot boot files (autoboot.txt, tryboot.txt)
IMAGE_INSTALL:append = " rpi-tryboot-files"

# No U-Boot storage variant builds needed (EEPROM handles all storage natively)
UBOOT_ENV_VARIANTS = ""
