# Replaces wic's implicit pull on the bootloader deploy artifacts
# (idbloader.img, u-boot.itb). meta-rockchip's rockchip-wic.inc adds "wic"
# to IMAGE_FSTYPES (transitively required from rk3588.inc); avocado-rockchip.inc
# removes it, so the bootloader deploy must be pinned here directly --
# stone bundle reads these files from ${DEPLOY_DIR_IMAGE}. The u-boot deploy
# transitively pulls trusted-firmware-a:do_deploy and rockchip-rkbin:do_deploy
# (the BL31/TPL blobs baked into u-boot.itb).
do_compile[depends] += "u-boot:do_deploy"

# Tools the stone/${MACHINE_SHORT_NAME}/build-disk-image.sh helper invokes
# (jq, sgdisk, mkfs.fat, mcopy/mmd, dd, truncate). dd/truncate come from
# coreutils-native which is in DEPENDS via inherit deploy.
DEPENDS += " jq-native gptfdisk-native dosfstools-native mtools-native"

# Shared GPT image-build helper shipped in the layer's
# stone/${MACHINE_SHORT_NAME}/ directory (auto-discovered by stone.bbclass's
# FILESEXTRAPATHS prepend).
#
# extlinux.conf is NOT shipped here -- u-boot's extlinux.bbclass (pulled
# in by meta-rockchip's rockchip-extlinux.inc via rk3588.inc) auto-generates
# and deploys it from UBOOT_EXTLINUX_* variables. avocado-rockchip.inc
# overrides those vars to match our partition layout. Two recipes deploying
# the same file would collide on do_deploy.
SRC_URI += " \
    file://build-disk-image.sh \
"

do_deploy:append() {
    install -d ${DEPLOYDIR}
    install -m 0755 ${WORKDIR}/build-disk-image.sh ${DEPLOYDIR}/build-disk-image.sh
}
