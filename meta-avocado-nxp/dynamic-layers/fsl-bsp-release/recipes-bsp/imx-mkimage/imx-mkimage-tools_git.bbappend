# With meta-imx in the build, imx-boot is packed by meta-imx's imx-mkimage, not
# meta-freescale's. Pack the SDK's tools from the same source, so a re-keyed
# imx-boot matches the distro's: the packers stamp their commit into every
# image (mkimage -commit). Keep in step with meta-imx-bsp's imx-mkimage_git.inc.
SRCBRANCH = "lf-6.18.20_2.0.0"
SRCREV = "1b577853ae1afe1f26cdef27548da52fb424af48"
