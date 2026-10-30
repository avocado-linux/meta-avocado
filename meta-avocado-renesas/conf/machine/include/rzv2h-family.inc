require conf/machine/include/soc-family.inc
SOC_FAMILY = "rzv2h-family:mali-family"

MACHINE_FEATURES = "opengles opencl mali-g31"

# Linux kernel configuration. RZ/V2H (r9a09g057) reaches mainline at v6.12; the
# BSP ships linux-renesas 6.1 and 6.12 (rz-6.12-cip7). Default the family to 6.12.
PREFERRED_PROVIDER_virtual/kernel ?= "linux-renesas"
PREFERRED_VERSION_linux-renesas ?= "6.12%"
KERNEL_IMAGETYPE ?= "Image"
