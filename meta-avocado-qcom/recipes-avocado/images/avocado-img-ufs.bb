DESCRIPTION = "Avocado qcom UFS bootfiles archive — per-machine static partition \
sources (bootloader, firmware, GPT, programmers, partition XMLs, dtb/efi/etc.) \
that stone-provision-ufs.sh extracts and combines with avocado-cli's runtime- \
built rootfs/var images at provision time."
LICENSE = "Apache-2.0"

PV = "${DISTRO_VERSION}"
# Bump when the bootfiles content changes but PV does not, so avocado build/
# provision gets a new NEVRA instead of reusing the cached archive. r1: dtb.bin
# is now a FAT holding the FIT (qclinux_fit.img) instead of a raw dtb -- the
# provisioned dtb_a must carry the new FIT for the board to boot the FIT path.
PR = "r1"

AVOCADO_PKG_IMG_RECIPE = "avocado-image-rootfs"
AVOCADO_PKG_IMG_NAME = "${AVOCADO_PKG_IMG_RECIPE}-${MACHINE_SHORT_NAME}.bootfiles.tar.gz"
AVOCADO_PKG_IMG_DEPTASK = "do_deploy_fixup"

inherit package-image
