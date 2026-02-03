# Depend on tegraflash-bsp and tools for BSP files deployment
# Use do_compile[depends] so files are deployed before do_collect_artifacts runs
do_compile[depends] += "tegraflash-bsp:do_deploy"
do_compile[depends] += "tegraflash-tools-deploy:do_deploy"
# Depend on tegra-initrd-flash-initramfs for tegraflash provisioning (needed by SDK)
do_compile[depends] += "tegra-initrd-flash-initramfs:do_image_complete"
AVOCADO_IMG_BOOTFILES_SKIP_EXTRA += " modules"

# Override default skip patterns to allow tegra-initrd-flash-initramfs through
# The default "initramfs" pattern skips ALL initramfs files including the tegraflash one we need
# Use more specific patterns: skip avocado-image-initramfs but allow tegra-initrd-flash-initramfs
AVOCADO_IMG_BOOTFILES_SKIP_DEFAULT = "rootfs avocado-image-initramfs var. -var-"
