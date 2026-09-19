DESCRIPTION = "Avocado qcom UFS bootfiles archive — per-machine static partition \
sources (bootloader, firmware, GPT, programmers, partition XMLs, dtb/efi/etc.) \
that stone-provision-ufs.sh extracts and combines with avocado-cli's runtime- \
built rootfs/var images at provision time."
LICENSE = "Apache-2.0"

PV = "${DISTRO_VERSION}"
# Per-machine bootfiles revision.
#
# This recipe is shared by every stone-ufs machine (avocado-stone.bbappend
# depends on it), so a bare `PR =` bump would give ALL of them a new NEVRA and
# force a full bootfiles re-download even when only one machine's content
# changed. Scope the bump with PR:<machine> so only the affected machine moves.
#
# Bump the machine-scoped PR whenever that machine's staged bootfiles change but
# PV (=DISTRO_VERSION) does not, so avocado build/provision gets a new NEVRA
# instead of reusing the cached archive. The dtb.bin assembly in
# image-avocado-qcom-deploy.bbclass (do_deploy_fixup) is now byte-reproducible,
# so the archive changes only when its inputs actually change.
#
# ponytail: manual, unenforced bump -- a content-derived release field (short
# checksum over the bootfiles tarball) would move the NEVRA automatically and is
# the right follow-up; kept manual here to keep this fix focused.
#
# r1 (rb3gen2): dtb.bin is now a FAT holding the FIT (qclinux_fit.img) instead of
# a raw dtb -- the provisioned dtb_a must carry the new FIT to boot the FIT path.
PR:rb3gen2 = "r1"

AVOCADO_PKG_IMG_RECIPE = "avocado-image-rootfs"
AVOCADO_PKG_IMG_NAME = "${AVOCADO_PKG_IMG_RECIPE}-${MACHINE_SHORT_NAME}.bootfiles.tar.gz"
AVOCADO_PKG_IMG_DEPTASK = "do_deploy_fixup"

inherit package-image
