PREFERRED_VERSION_linux-raspberrypi ?= "6.12.%"

UBOOT_ENV_SIZE = "0x20000"

IMAGE_BOOT_FILES:append = " avocado-image-initramfs-${MACHINE}.cpio.zst;avocado-initramfs.cpio.zst"

RPI_USE_U_BOOT = "1"
ENABLE_DWC2_HOST = "1"

CMDLINE_ROOT_PARTITION = "/dev/mmcblk0p2"
CMDLINE_ROOT_FSTYPE = "rootfstype=erofs"
CMDLINE:append = " audit=0"

# What this machine can deliver on the security side. Explicitly nothing, not
# unset: the declaration is what pulls a capability's tooling into the feed
# (docs/security-capabilities.md), and encrypted-var is not deliverable here
# yet - linux-raspberrypi carries no dm-crypt fragment, and the MBR layout
# (stone/rpi/rootdisk.conf) has no `var` PARTLABEL for cryptsetup-var.service
# to key on. Declaring it anyway would ship a unit that waits on a device this
# machine never produces. Declare it once both are wired.
#
# A third gap sits behind those two even once fixed: no var-key provider
# exists for this machine that can derive a device-unique key without
# reading a secret from inside /var. See
# recipes-core/cryptsetup-var/README-deliverability.md for the full
# enumeration of what deliverability requires per machine.
AVOCADO_SECURITY_CAPABILITIES = ""

# The plaintext var partition; /var mounts /dev/disk/by-avocado/var, which
# resolves here. A raw node rather than /dev/disk/by-partlabel/var: MBR carries
# no GPT PARTLABEL.
AVOCADO_VAR_PART_DEV = "/dev/mmcblk0p3"

DEPENDS:append:pn-mesa = " libxshmfence"
