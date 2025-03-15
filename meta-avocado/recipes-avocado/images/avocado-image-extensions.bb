DESCRIPTION = "Avocado extensions package image"
LICENSE = "Apache-2.0"

inherit nopackages

IMAGE_FSTYPES = ""
IMAGE_FEATURES = ""

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

EXCLUDE_FROM_WORLD = "1"

IMAGE_INSTALL = "packagegroup-avocado-extensions"
