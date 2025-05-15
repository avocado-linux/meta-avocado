DESCRIPTION = "Packagegroup for Avocado SDK"
LICENSE = "Apache-2.0"

inherit packagegroup

RDEPENDS:${PN} = " \
  avocado-sdk-toolchain \
  nativesdk-avocado-pkg-bootfiles \
  nativesdk-avocado-pkg-img-initramfs \
  nativesdk-avocado-pkg-img-rootfs \
  nativesdk-avocado-pkg-img-var \
  ${VIRTUAL-RUNTIME_avocado-sdk-metadata} \
"
