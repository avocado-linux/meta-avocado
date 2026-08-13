# Pin imx-mkimage (used by imx-boot) to the lf-6.12.49_2.2.0 branch for the
# i.MX95 FRDM board.  The meta-imx recipe uses lf-6.6.36_2.1.0 whose
# iMX95/soc.mak defaults LPDDR_FW_VERSION to _v202311.  The newer branch
# defaults to _v202409, which matches the DDR blobs shipped in firmware-imx
# 8.31 and used by the reference build script.
SRCBRANCH:avocado-imx95-frdm = "lf-6.12.49_2.2.0"
SRCREV:avocado-imx95-frdm = "be80fadd5e7988214149a2bc48daac1b0950d4c2"

# AHAB signing, i.MX93 only for now. Required rather than conditionally
# included on an override so that a machine which lacks the wiring but is given
# the feature fails at parse instead of silently deploying unsigned.
require ${@ 'imx-boot-ahab-sign.inc' if bb.utils.contains('DISTRO_FEATURES', 'ahab', True, False, d) else ''}
