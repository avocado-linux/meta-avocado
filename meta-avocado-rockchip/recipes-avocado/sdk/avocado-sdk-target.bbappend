FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

# Same deploy chain as avocado-stone.bbappend so the SDK build sees
# idbloader.img / u-boot.itb under DEPLOY_DIR_IMAGE.
do_compile[depends] += "u-boot:do_deploy"

# nativesdk versions of the tools build-disk-image.sh invokes when run
# from inside the SDK container (jq, sgdisk, mkfs.fat, mcopy/mmd).
RDEPENDS:${PN}:append = " \
  nativesdk-jq \
  nativesdk-gptfdisk \
  nativesdk-dosfstools \
  nativesdk-mtools \
"
