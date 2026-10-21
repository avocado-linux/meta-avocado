# Ship the bootloader and firmware this package collects from the deploy dir as
# direct dependencies. Reaching them only through avocado-stone or
# rpi-bootfiles is not enough: with hash equivalence, a rebuild of U-Boot, of
# config.txt (rpi-config) or of cmdline.txt (rpi-cmdline) leaves those
# recipes' outputs unchanged, so sstate served this package with the previous
# file.
do_compile[depends] += "u-boot:do_deploy rpi-bootfiles:do_deploy rpi-config:do_deploy rpi-cmdline:do_deploy"
