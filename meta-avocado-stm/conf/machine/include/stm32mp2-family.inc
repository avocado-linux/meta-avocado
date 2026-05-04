# Shared bring-up settings for the stm32mp2 SoC family.
#
# Pulled into every avocado-stm32mp2-*.conf so the kernel/bootloader/imaging
# defaults stay consistent across boards in the family. Per-board overrides
# (DTBs, MACHINE_FEATURES, EXTRA_IMAGEDEPENDS for board-specific firmware)
# stay in the machine .conf.

# Vendor BSP providers from meta-st-stm32mp.
PREFERRED_PROVIDER_virtual/kernel ?= "linux-stm32mp"
PREFERRED_PROVIDER_virtual/bootloader ?= "u-boot-stm32mp"

# Build a flat Image plus the gzip variant. The FAT boot partition references
# Image directly so U-Boot's booti can hand off without intermediate decompress.
KERNEL_IMAGETYPE ?= "Image"
KERNEL_IMAGETYPES ?= "Image Image.gz"

# Compile DTBs with symbols so U-Boot can apply overlays at runtime via
# `fdt apply` / extlinux.conf `fdtoverlays`. Without -@, the base DTB lacks
# the __symbols__ node and overlays referenced by extlinux.conf silently
# fail to apply.
KERNEL_DTC_FLAGS += "-@"
