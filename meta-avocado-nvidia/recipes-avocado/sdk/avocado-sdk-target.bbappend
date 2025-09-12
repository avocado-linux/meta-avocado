FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

RDEPENDS:${PN}:append = " \
  nativesdk-jq \
  nativesdk-coreutils \
  nativesdk-util-linux \
  nativesdk-util-linux-getopt \
  nativesdk-qemu-system-x86-64 \
  nativesdk-python3-pyyaml \
"
