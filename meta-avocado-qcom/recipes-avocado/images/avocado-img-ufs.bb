DESCRIPTION = "Avocado qcom UFS bootfiles archive — per-machine static partition \
sources (bootloader, firmware, GPT, programmers, partition XMLs, dtb/efi/etc.) \
that stone-provision-ufs.sh extracts and combines with avocado-cli's runtime- \
built rootfs/var images at provision time."
LICENSE = "Apache-2.0"

PV = "${DISTRO_VERSION}"

AVOCADO_PKG_IMG_RECIPE = "avocado-image-rootfs"
AVOCADO_PKG_IMG_NAME = "${AVOCADO_PKG_IMG_RECIPE}-${MACHINE_SHORT_NAME}.bootfiles.tar.gz"
AVOCADO_PKG_IMG_DEPTASK = "do_deploy_fixup"

inherit package-image
