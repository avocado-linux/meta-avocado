# Common settings for Avocado arm64 UEFI machines: ACPI/UEFI systems
# (SBSA-style servers and workstations such as Grace, DGX Spark/GB10, Neoverse
# N2/V2) that boot systemd-boot from an A/B pair of ESPs, as the x86-64
# machines do. Boards are BSP extensions on top; nothing here is board-specific.

MACHINEOVERRIDES =. "arm64-uefi:"

KERNEL_IMAGETYPE = "Image"

# No fixed serial getty: the UART differs per system (ttyAMA0 on PL011, ttyS0
# on 16550-compatibles like the GB10's MediaTek 8250, or none), and a
# serial-getty for an absent tty holds boot for the 90 s device timeout, as
# ttyS0 did on the first Spark boot. The kernel takes its console from the ACPI
# SPCR table, and systemd-getty-generator starts a getty on it when present.
SERIAL_CONSOLES = ""

MACHINE_FEATURES += "efi pci"

EFI_PROVIDER = "systemd-boot"
AVOCADO_BOOTLOADER = "uefi"

# The plaintext var partition. /var actually mounts /dev/disk/by-avocado/var,
# which resolves here unless the initrd opened a LUKS mapping over it
# (docs/security-capabilities.md).
AVOCADO_VAR_PART_DEV = "/dev/disk/by-partlabel/var"

# Ensure kernel modules are built as packages (loadable, not built-in)
MACHINE_EXTRA_RRECOMMENDS += "kernel-modules"

# NVIDIA GPU driver stack (open kernel modules + libcuda + nvidia-smi + GSP
# firmware) from meta-avocado-shared, as on x86-64: always in the feed, so
# discrete GPUs on arm64 servers and the GB10 iGPU work from a BSP extension.
# Harmless where there is no NVIDIA GPU -- the modules just don't load.
PKG_EXTRA_INSTALL:append = " packagegroup-avocado-nvidia-gpu"

# The kernel-module-nvidia* packages are produced dynamically by the
# out-of-tree nvidia-gpu-modules recipe, which the packages-only feed image
# does not pull in by itself; see avocado-x86-64.inc for the mechanism.
IMAGE_PACKAGES_ONLY_FORCE_PROVIDERS:append:pn-avocado-pkg-extra = " nvidia-gpu-modules"
