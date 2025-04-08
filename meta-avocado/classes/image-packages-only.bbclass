# packages-only.bbclass
#
# Class for recipes where only packages are desired, without producing any image output
# This disables all image generation tasks while preserving package building

inherit image

# Disable image generation tasks
do_rootfs[noexec] = "1"
do_rootfs_wicenv[noexec] = "1"
do_image[noexec] = "1"
do_image_wic[noexec] = "1"
do_image_complete[noexec] = "1"

# Disable all SPDX/SBOM generation tasks
do_create_rootfs_spdx[noexec] = "1"
do_create_image_spdx[noexec] = "1"
do_create_image_spdx_setscene[noexec] = "1"
do_create_rootfs_spdx_setscene[noexec] = "1"
do_create_image_sbom_spdx[noexec] = "1"

# Disable image-specific settings
IMAGE_FSTYPES = ""
IMAGE_FEATURES = ""

# Ensure these recipes are excluded from world builds
EXCLUDE_FROM_WORLD = "1"
