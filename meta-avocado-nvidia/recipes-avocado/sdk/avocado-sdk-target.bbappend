FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

RDEPENDS:${PN}:append = " \
  nativesdk-coreutils \
  nativesdk-util-linux \
  nativesdk-util-linux-getopt \
  nativesdk-util-linux-hexdump \
  nativesdk-util-linux-mount \
  nativesdk-util-linux-losetup \
  nativesdk-gptfdisk \
  nativesdk-qemu-system-x86-64 \
  nativesdk-python3-pyyaml \
  nativesdk-boardctl \
"
