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

# NVIDIA discrete-GPU driver stack (open kernel modules + libcuda + nvidia-smi +
# GSP firmware). Installed on all x86-64 targets so a *complete* build always
# builds the driver into the feed (and GPU-equipped boards work out of the box).
# Harmless on boards without an NVIDIA GPU -- the modules just don't load.
# Applies to v2/v3/v4 (all require this include). This replaces the ad-hoc
# per-machine kas local_conf_header that only covered v3.
PKG_EXTRA_INSTALL:append = " packagegroup-avocado-nvidia-gpu"
