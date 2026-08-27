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
# QCS6490 SoC firmware and userspace on the upstream BSP: linux-firmware's
# per-block qcm6490 packages (meta-lts-mixins 20260810), mesa/freedreno GPU,
# mainline venus video and audioreach audio. The meta-qcom-hwe packagegroups
# this listed before (packagegroup-firmware-qcm6490, -qcom-display/-graphics/
# -video) were the proprietary adreno/PAL stack and are gone with that layer.
RDEPENDS:${PN}:append:qcm6490 = " \
    linux-firmware-qcom-adreno-a660 \
    linux-firmware-qcom-qcm6490-adreno \
    linux-firmware-qcom-qcm6490-audio \
    linux-firmware-qcom-qcm6490-compute \
    linux-firmware-qcom-qcm6490-ipa \
    linux-firmware-qcom-qcm6490-qupv3fw \
    linux-firmware-qcom-qcm6490-wifi \
    linux-firmware-qcom-vpu \
    packagegroup-qcom-boot-essential \
    packagegroup-qcom-boot-additional \
    mesa \
    gstreamer1.0 \
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad \
    gstreamer1.0-rtsp-server \
    v4l-utils \
"
RDEPENDS:${PN}:append:rubikpi3 = " \
    firmware-rubikpi3 \
    linux-firmware-qcom-qcs6490-thundercomm-rubikpi3-audio \
    rubikpi-bt-staticdev \
    rubikpi-wifi \
    rubikpi3-init-services-bt \
    rubikpi3-init-services-wifi \
    rubikpi3-thermal \
    wiringrp \
    wiringrp-gpio \
    wiringrp-python \
"
