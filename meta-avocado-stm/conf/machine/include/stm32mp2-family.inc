# Shared bring-up settings for the stm32mp2 SoC family.
#
# Pulled into every avocado-stm32mp2-*.conf so the kernel/bootloader/imaging
# defaults stay consistent across boards in the family. Per-board overrides
# (DTBs, MACHINE_FEATURES, EXTRA_IMAGEDEPENDS for board-specific firmware)
# stay in the machine .conf.

# Vendor BSP providers from meta-st-stm32mp.
PREFERRED_PROVIDER_virtual/kernel ?= "linux-stm32mp"
PREFERRED_PROVIDER_virtual/bootloader ?= "u-boot-stm32mp"

# Don't override KERNEL_IMAGETYPE / KERNEL_IMAGETYPES here -- the upstream
# st-machine-common-stm32mp.inc sets KERNEL_IMAGETYPE = "Image.gz" and
# KERNEL_ALT_IMAGETYPE = "vmlinux Image", and kernel.bbclass merges all
# three into KERNEL_IMAGETYPES cleanly when nothing else has touched it.
# Setting KERNEL_IMAGETYPES explicitly here trips kernel.bbclass's merge
# logic (lines 74-83) which treats KERNEL_ALT_IMAGETYPE as a single token
# in `if alttype not in types.split()` and prepends the whole multi-word
# string, producing duplicates -> "kernel-image-image listed twice" QA fail.
# Both Image and Image.gz are deployed; the FAT boot partition references
# Image directly via the stone manifest.

# Compile DTBs with symbols so U-Boot can apply overlays at runtime via
# `fdt apply` / extlinux.conf `fdtoverlays`. Without -@, the base DTB lacks
# the __symbols__ node and overlays referenced by extlinux.conf silently
# fail to apply.
KERNEL_DTC_FLAGS += "-@"

# meta-st-stm32mp's flashlayout-stm32mp.bbclass is globally inherited via
# st-machine-common-stm32mp.inc (which we require for the OP-TEE/TF-A
# plumbing) and adds do_create_flashlayout_config to every recipe in the
# build. The task synthesizes ST-format .tsv flashlayouts that consume
# splitted-bootfs.ext4 / vendorfs.ext4 binaries the BSP's WIC pipeline
# produces -- a pipeline we suppress (WKS_FILE="") because we provision
# via stone instead. With no binaries to consume, the task fatals
# `No flashlayout file created`. Set noexec on every recipe so the task
# is a no-op everywhere it's been planted.
do_create_flashlayout_config[noexec] = "1"
do_create_flashlayout_config_setscene[noexec] = "1"
