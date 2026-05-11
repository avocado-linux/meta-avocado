FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"
FILESEXTRAPATHS:prepend := "${@':'.join(['%s/stone' % layer for layer in d.getVar('BBLAYERS').split()])}:"

# Same deploy chain as avocado-stone.bbappend so the SDK build sees
# idbloader.img / u-boot.itb under DEPLOY_DIR_IMAGE.
do_compile[depends] += "u-boot:do_deploy"

# Host tools the orangepi-5-plus provisioning scripts call.
#
# build-disk-image.sh    : jq, sgdisk, mkfs.fat, mcopy/mmd, truncate, dd
# stone-provision-sd.sh  : lsblk, blockdev, umount  (+ above)
# stone-provision-emmc.sh: rkdeveloptool             (+ above)
#
# Naming maps to nativesdk-* packages. coreutils provides dd/truncate; it's
# already pulled in by the base avocado-sdk-target recipe so we don't
# re-list it.
RDEPENDS:${PN}:append = " \
  nativesdk-jq \
  nativesdk-gptfdisk \
  nativesdk-dosfstools \
  nativesdk-mtools \
  nativesdk-util-linux-lsblk \
  nativesdk-util-linux-blockdev \
  nativesdk-util-linux-mount \
  nativesdk-rkdeveloptool \
"

# rkdeveloptool talks rockusb over USB; the SDK needs libusb at runtime.
DEPENDS:append:stone-emmc = " nativesdk-libusb1"
RDEPENDS:${PN}:append:stone-emmc = " nativesdk-libusb1"
