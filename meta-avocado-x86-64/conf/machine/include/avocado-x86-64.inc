# Common settings for Avocado x86-64 machines (Intel and AMD)

MACHINEOVERRIDES =. "avocado-x86-64:"

KERNEL_IMAGETYPE = "bzImage"

SERIAL_CONSOLES ?= "115200;ttyS0"

EFI_PROVIDER = "systemd-boot"
AVOCADO_BOOTLOADER = "uefi"

# Same pattern as qemuarm64/qemux86-64/imx93-frdm: point /var at the dm-crypt
# mapping only when encrypted-var is actually on. Without this line
# AVOCADO_VAR_PART_DEV fell through to base-files' own default
# (PARTUUID=4d21b016-..., the raw partition), which never resolves to
# /dev/mapper/var - so enabling encrypted-var on an x86-64 target would open
# the LUKS container while fstab kept mounting the plaintext partition
# underneath it, and cryptsetup-var-udev would never get pulled in either
# (packagegroup-avocado-rootfs.bb gates it on this same variable).
AVOCADO_VAR_PART_DEV = "${@bb.utils.contains('DISTRO_FEATURES', 'encrypted-var', '/dev/mapper/var', '/dev/disk/by-partlabel/var', d)}"

MACHINE_ESSENTIAL_EXTRA_RDEPENDS += "v86d"

# Ensure kernel modules are built as packages (loadable, not built-in)
MACHINE_EXTRA_RRECOMMENDS += "kernel-modules"
