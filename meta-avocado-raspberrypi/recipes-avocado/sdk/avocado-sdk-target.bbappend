FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"
FILESEXTRAPATHS:prepend := "${@':'.join(['%s/stone' % layer for layer in d.getVar('BBLAYERS').split()])}:"

do_compile[depends] += "u-boot:do_deploy"
do_compile[depends] += "rpi-bootfiles:do_deploy"

# Stage the boot artifacts stone-raspberrypi<n>.json names but this build does
# not produce: u-boot.bin (-> kernel_<soc>.img) and the whole bootfiles/ set
# (start*.elf, fixup*.dat, bootcode.bin, config.txt, cmdline.txt).
#
# The two dependencies above already force those recipes to deploy, but nothing
# copied the result anywhere stone could see it, so the dependency was declared
# and never used. The runtime input dir only holds what the runtime build makes
# (rootfs, kernel, initramfs, var), so `avocado build` died at finalize with
# "File 'u-boot.bin' not found in any input directory for FAT image".
#
# They go beside the manifest that names them, in the SDK's stone dir, which the
# CLI passes to `stone bundle` as an input directory. Reading DEPLOY_DIR_IMAGE
# here is safe precisely because of the do_deploy dependencies above - without
# them this would be a race rather than a copy.
do_install:append() {
    install -d ${D}${SDKPATHNATIVE}/stone
    install -m 0644 ${DEPLOY_DIR_IMAGE}/u-boot.bin ${D}${SDKPATHNATIVE}/stone/u-boot.bin

    install -d ${D}${SDKPATHNATIVE}/stone/bootfiles
    cp -a ${DEPLOY_DIR_IMAGE}/bootfiles/. ${D}${SDKPATHNATIVE}/stone/bootfiles/
}

RDEPENDS:${PN}:append = " \
  nativesdk-fwup \
  nativesdk-mkfat \
  nativesdk-rpi-usbboot \
"
