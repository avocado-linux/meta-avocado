FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

RDEPENDS:${PN}:append = " \
  nativesdk-jq \
  nativesdk-coreutils \
  nativesdk-util-linux \
  nativesdk-util-linux-getopt \
  nativesdk-util-linux-hexdump \
  nativesdk-util-linux-mount \
  nativesdk-gptfdisk \
  nativesdk-qemu-system-x86-64 \
  nativesdk-python3-pyyaml \
"

SRC_URI:append = " file://avocado-deploy-jetson"

do_install:append() {
  install -m 755 ${WORKDIR}/avocado-deploy-jetson ${D}${SDKPATHNATIVE}${bindir}/avocado-deploy-${MACHINE_SHORT_NAME}
}

FILES:${PN}:append = " ${SDKPATHNATIVE}${bindir}/avocado-deploy-${MACHINE_SHORT_NAME}"
