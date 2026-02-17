# Common settings for Avocado x86-64 machines (Intel and AMD)

MACHINEOVERRIDES =. "avocado-x86-64:"

KERNEL_IMAGETYPE = "bzImage"

SERIAL_CONSOLES ?= "115200;ttyS0"

EFI_PROVIDER = "systemd-boot"

MACHINE_ESSENTIAL_EXTRA_RDEPENDS += "v86d"

# Ensure kernel modules are built as packages (loadable, not built-in)
MACHINE_EXTRA_RRECOMMENDS += "kernel-modules"
