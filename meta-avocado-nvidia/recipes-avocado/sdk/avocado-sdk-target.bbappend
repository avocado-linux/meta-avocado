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

# Shared boot.img packer for the A_kernel/B_kernel partitions, called by the
# Jetson build hooks (OTA payload) and stone-provision-tegraflash.sh (flash).
SRC_URI += "file://avocado-tegra-bootimg"
FILES:${PN} += "${SDKPATHNATIVE}${bindir}/avocado-tegra-bootimg"
do_install:append() {
    install -m 0755 ${UNPACKDIR}/avocado-tegra-bootimg ${D}${SDKPATHNATIVE}${bindir}
}
