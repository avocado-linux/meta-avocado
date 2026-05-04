DESCRIPTION = "Feed-only extras for qcom targets — built and published to the \
package feed, NOT installed in the base rootfs. The BSP extension \
(bsp/<machine>/avocado.yaml) cherry-picks what to install on-device."
LICENSE = "Apache-2.0"

# Per-machine packaging so MACHINE-conditional overrides take effect and the
# resulting RPM doesn't get deduped across machines with different RDEPENDS.
PACKAGE_ARCH = "${MACHINE_ARCH}"

inherit packagegroup
PROVIDES = "${PACKAGES}"
PACKAGES = "${PN}"

# kernel-modules pulls every kernel-module-* into the feed so BSP extensions
# can install individual drivers on demand. MACHINE_EXTRA_RRECOMMENDS expands
# per-machine for board-specific module/firmware bundles.
RDEPENDS:${PN} = " \
    kernel-modules \
    ${MACHINE_EXTRA_RRECOMMENDS} \
"

# Qualcomm SoC firmware + GPU/display/video/graphics/multimedia stack — heavy
# graphics packages staged in the feed; the BSP extension installs them when
# the user actually wants display, video accelerator, etc.
RDEPENDS:${PN}:append:qcm6490 = " \
    packagegroup-firmware-qcm6490 \
    packagegroup-qcom-data \
    packagegroup-qcom-display \
    packagegroup-qcom-graphics \
    packagegroup-qcom-video \
    gstreamer1.0 \
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad \
    gstreamer1.0-rtsp-server \
    v4l-utils \
"

# RUBIK Pi 3 onboard peripheral firmware (Wi-Fi, HDMI bridge, audio amp,
# USB hub) — packaged from board-supplied blobs (recipes-firmware/firmware-rubikpi3).
RDEPENDS:${PN}:append:rubikpi3 = " firmware-rubikpi3"
