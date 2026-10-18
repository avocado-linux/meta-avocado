PREFERRED_VERSION_linux-raspberrypi ?= "6.12.%"

UBOOT_ENV_SIZE = "0x20000"

IMAGE_BOOT_FILES:append = " avocado-image-initramfs-${MACHINE}.cpio.zst;avocado-initramfs.cpio.zst"

RPI_USE_U_BOOT = "1"
ENABLE_DWC2_HOST = "1"

CMDLINE_ROOT_PARTITION = "/dev/mmcblk0p2"
CMDLINE_ROOT_FSTYPE = "rootfstype=erofs"
CMDLINE:append = " audit=0"

# What this machine can deliver on the security side; the declaration is what
# pulls a capability's tooling into the feed (docs/security-capabilities.md).
# encrypted-var: linux-raspberrypi carries the dm-crypt fragment
# (avocado-security-kernel.inc), and cryptsetup-var opens the MBR var
# partition by its raw node, AVOCADO_VAR_PART_DEV below
# (avocado-var-device.bbclass). There is no TPM or key-wrapping engine, so a
# runtime with var.hardware auto unlocks with the Argon2id key var-key.sh
# derives from the board serial: encryption at rest, not bound to hardware.
AVOCADO_SECURITY_CAPABILITIES = "encrypted-var"

# The plaintext var partition; /var mounts /dev/disk/by-avocado/var, which
# resolves here. A raw node rather than /dev/disk/by-partlabel/var: MBR carries
# no GPT PARTLABEL.
AVOCADO_VAR_PART_DEV = "/dev/mmcblk0p3"

DEPENDS:append:pn-mesa = " libxshmfence"
