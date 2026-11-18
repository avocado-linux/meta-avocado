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
  nativesdk-dtc \
  nativesdk-avocado-dtc-overlay \
"

# nativesdk-avocado-dtc-overlay compiles the device-tree overlays a project
# declares with a `src`; the delivery hook (avocado-dtc-overlay-deliver, Orin
# only) merges them. The wrapper only compiles, so it is not gated by SoC.
# DEPENDS as well as RDEPENDS: RDEPENDS alone records the requirement without
# building the provider, so it never reaches the SDK feed and `avocado install`
# fails with "No match for argument: nativesdk-avocado-dtc-overlay".
DEPENDS:append = " nativesdk-avocado-dtc-overlay"

# Shared boot.img packer for the A_kernel/B_kernel partitions, called by the
# Jetson build hooks (OTA payload) and stone-provision-tegraflash.sh (flash).
SRC_URI += "file://avocado-tegra-bootimg file://avocado-tegra-build-bootimg"
FILES:${PN} += "${SDKPATHNATIVE}${bindir}/avocado-tegra-bootimg ${SDKPATHNATIVE}${bindir}/avocado-tegra-build-bootimg"
do_install:append() {
    install -m 0755 ${UNPACKDIR}/avocado-tegra-bootimg ${D}${SDKPATHNATIVE}${bindir}
    install -m 0755 ${UNPACKDIR}/avocado-tegra-build-bootimg ${D}${SDKPATHNATIVE}${bindir}
}
