DESCRIPTION = "Packagegroup for inclusion in Avocado Rockchip SDKs"
LICENSE = "Apache-2.0"

inherit packagegroup

# Mirrors RDEPENDS in recipes-avocado/sdk/avocado-sdk-target.bbappend.
# Pulled into the SDK image via SDK_PKG_EXTRA_INSTALL in
# kas/vendor/rockchip.yml so users running stone provision scripts from
# inside the SDK container have all the host tools.
RDEPENDS:${PN} = " \
  nativesdk-jq \
  nativesdk-gptfdisk \
  nativesdk-dosfstools \
  nativesdk-mtools \
  nativesdk-util-linux-lsblk \
  nativesdk-util-linux-blockdev \
  nativesdk-util-linux-mount \
  nativesdk-rkdeveloptool \
"
