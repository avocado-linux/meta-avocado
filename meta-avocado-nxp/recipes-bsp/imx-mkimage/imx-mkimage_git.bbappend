# Keep the native imx-mkimage tool in sync with the imx-boot recipe source for
# the i.MX95 FRDM board.  Both recipes share imx-mkimage_git.inc; override here
# so the native build also uses lf-6.12.49_2.2.0.
SRCBRANCH:avocado-imx95-frdm = "lf-6.12.49_2.2.0"
SRCREV:avocado-imx95-frdm = "be80fadd5e7988214149a2bc48daac1b0950d4c2"
