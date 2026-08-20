PREFERRED_VERSION_linux-raspberrypi ?= "6.12.%"

UBOOT_ENV_SIZE = "0x20000"

IMAGE_BOOT_FILES:append = " avocado-image-initramfs-${MACHINE}.cpio.zst;avocado-initramfs.cpio.zst"

RPI_USE_U_BOOT = "1"
ENABLE_DWC2_HOST = "1"

CMDLINE_ROOT_PARTITION = "/dev/mmcblk0p2"
CMDLINE_ROOT_FSTYPE = "rootfstype=erofs"
CMDLINE:append = " audit=0"

# One declaration of what this machine can deliver on the security side, read
# by avocado-security-capabilities.bbclass before any DISTRO_FEATURES request
# is honoured.
AVOCADO_SECURITY_CAPABILITIES = "encrypted-var"

# /var is a LUKS2 container that cryptsetup-var.service formats (first boot) and
# opens in the initramfs. Mount /var from the dm-crypt mapper rather than the raw
# partition: var.mount then implicitly orders after dev-mapper-var.device, which
# only appears once cryptsetup-var has opened the container - so the mount waits
# for the unlock instead of racing it and dropping to emergency mode. Unlike
# avocado-qemuarm64/qemux86-64/imx93-frdm, the non-encrypted-var branch stays the
# raw /dev/mmcblk0p3 rather than /dev/disk/by-partlabel/var: this machine is
# MBR-partitioned (stone/rpi/rootdisk.conf), which carries no GPT PARTLABEL, so a
# by-partlabel path would not resolve here.
AVOCADO_VAR_PART_DEV = "${@bb.utils.contains('DISTRO_FEATURES', 'encrypted-var', '/dev/mapper/var', '/dev/mmcblk0p3', d)}"

DEPENDS:append:pn-mesa = " libxshmfence"
