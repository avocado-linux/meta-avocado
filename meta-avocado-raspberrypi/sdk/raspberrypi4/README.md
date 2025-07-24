# Testing

# Generater the boot.img

```
cat meta-avocado-raspberrypi/sdk/raspberrypi4/manifest.json | jq .storage_devices.rootdisk.images.boot | mkfat --base $PWD/build-raspberrypi4/build/tmp/deploy/images/avocado-raspberrypi4 --output $PWD/build-raspberrypi4/build/tmp/deploy/images/avocado-raspberrypi4/boot.img --size-mb 128
```

# Generate the fwup conf

```
AVOCADO_SDK_RUNTIME_DIR="$PWD/build-raspberrypi4/build/tmp/deploy/images/avocado-raspberrypi4" \
AVOCADO_IMAGE_UBOOT_ENV="uboot.env" \
AVOCADO_IMAGE_BOOT="boot.img" \
AVOCADO_IMAGE_ROOTFS="avocado-image-rootfs-avocado-raspberrypi4.rootfs.squashfs" \
AVOCADO_IMAGE_VAR="avocado-image-var-avocado-raspberrypi4.btrfs" \
AVOCADO_OS_CODENAME="apollo/edge" \
AVOCADO_OS_DESCRIPTION="Avocado Apollo" \
AVOCADO_OS_VERSION="0.1.0" \
AVOCADO_OS_PLATFORM="raspberrypi4" \
AVOCADO_OS_ARCHITECTURE="aarch64" \
AVOCADO_OS_AUTHOR="Avocado Team" \
AVOCADO_PARTITION_UBOOT_ENV_OFFSET=2048 \
AVOCADO_PARTITION_UBOOT_ENV_OFFSET_REDUND=2304 \
AVOCADO_PARTITION_UBOOT_ENV_BLOCKS=256 \
AVOCADO_PARTITION_BOOTFS_OFFSET=4096 \
AVOCADO_PARTITION_BOOTFS_BLOCKS=262144 \
AVOCADO_PARTITION_RECOVERY_OFFSET=528384 \
AVOCADO_PARTITION_RECOVERY_BLOCKS=262144 \
AVOCADO_PARTITION_ROOTFS_OFFSET=790528 \
AVOCADO_PARTITION_ROOTFS_BLOCKS=327680 \
AVOCADO_PARTITION_VAR_OFFSET=1445888 \
AVOCADO_PARTITION_VAR_BLOCKS=262144 \
fwup -c -f $PWD/meta-avocado-raspberrypi/sdk/raspberrypi4/rootdisk.conf -o $PWD/build-raspberrypi4/build/tmp/deploy/images/avocado-raspberrypi4/rootdisk.zip
```

```
fwup -a -i $PWD/build-raspberrypi4/build/tmp/deploy/images/avocado-raspberrypi4/rootdisk.zip -t complete -d $PWD/build-raspberrypi4/build/tmp/deploy/images/avocado-raspberrypi4/rootdisk.img
```
