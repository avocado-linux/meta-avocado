FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

RDEPENDS:${PN}:append = " \
  nativesdk-coreutils \
  nativesdk-util-linux \
  nativesdk-util-linux-getopt \
  nativesdk-util-linux-hexdump \
  nativesdk-util-linux-mount \
  nativesdk-gptfdisk \
  nativesdk-qemu-system-x86-64 \
  nativesdk-python3-pyyaml \
  nativesdk-boardctl \
"

# Stage the Tegra BSP into the SDK's stone dir.
#
# avocado-cli adds $AVOCADO_SDK_PREFIX/stone as a stone input dir precisely so a
# BSP's stone-<arch>.json can reference boot artifacts the runtime build does not
# produce. Its own comment (runtime/build.rs) calls that "the consumer half of a
# two-part change ... inert without the other: today meta-avocado's
# avocado-sdk-target installs only the stone JSON into this directory". This is
# the other half.
#
# Without it, anything that needs a BSP artifact at CLI build time cannot see
# one. The device-tree overlay hook is the first consumer - it has to read the
# base DTB to merge overlays into it - and it fails with "tegraflash_bsp
# directory not found". The same gap is what stops a manifest naming u-boot.bin
# or bootfiles/ from resolving, so this is deliberately the whole BSP rather
# than only the DTB the overlay path happens to need.
#
# The cost is real and accepted: the BSP is several hundred files including the
# flashing binaries, and it lands in every Jetson SDK image.
do_install[depends] += "tegraflash-bsp:do_deploy"

do_install:append() {
    if [ -d ${DEPLOY_DIR_IMAGE}/tegraflash-bsp ]; then
        install -d ${D}${SDKPATHNATIVE}/stone/tegraflash-bsp
        # -a to keep symlinks and modes, then normalise ownership: the deploy
        # dir is owned by the build user, and do_package rejects a packaged path
        # whose uid has no passwd entry ("getpwuid(): uid not found").
        cp -a ${DEPLOY_DIR_IMAGE}/tegraflash-bsp/. ${D}${SDKPATHNATIVE}/stone/tegraflash-bsp/
        chown -R root:root ${D}${SDKPATHNATIVE}/stone/tegraflash-bsp
        bbnote "staged $(find ${D}${SDKPATHNATIVE}/stone/tegraflash-bsp -type f | wc -l) BSP files into the SDK stone dir"
    else
        bbfatal "tegraflash-bsp not in ${DEPLOY_DIR_IMAGE}; the SDK stone dir would ship without the BSP and every consumer of a BSP artifact would fail at CLI build time with a not-found that points at the SDK rather than at this recipe"
    fi
}
