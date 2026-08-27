# Common settings for Avocado x86-64 machines (Intel and AMD)

MACHINEOVERRIDES =. "avocado-x86-64:"

KERNEL_IMAGETYPE = "bzImage"

SERIAL_CONSOLES ?= "115200;ttyS0"

EFI_PROVIDER = "systemd-boot"
AVOCADO_BOOTLOADER = "uefi"

# The plaintext var partition. /var actually mounts /dev/disk/by-avocado/var,
# which resolves here unless the initrd opened a LUKS mapping over it
# (docs/security-capabilities.md).
AVOCADO_VAR_PART_DEV = "/dev/disk/by-partlabel/var"

MACHINE_ESSENTIAL_EXTRA_RDEPENDS += "v86d"

# Ensure kernel modules are built as packages (loadable, not built-in)
MACHINE_EXTRA_RRECOMMENDS += "kernel-modules"
