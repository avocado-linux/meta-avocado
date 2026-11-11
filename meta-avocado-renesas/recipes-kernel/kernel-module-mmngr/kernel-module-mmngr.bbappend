# meta-rzv2n swaps meta-rz-drpai's mmngr bug-fix patch for a -solidrun copy
# that fixed its copy_from_user calls, removing it by its pre-V1.50 name
# (0009-). V1.50 renamed it 0001- and fixed copy_from_user itself, so both
# end up applied and the SolidRun copy fails. Keep Renesas's: it also uses
# the conventional DMA directions (flush TO_DEVICE, invalidate FROM_DEVICE).
SRC_URI:remove:rzv2n-sr-som = "file://0009-kernel-module-mmngr-bug-fix-solidrun.patch"
