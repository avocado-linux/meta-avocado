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
# mainline venus video and APR/QDSP6 audio (apr + q6core/q6afe/q6asm/q6adm --
# not audioreach, which is for the gpr-based SoCs). The meta-qcom-hwe packagegroups
# this listed before (packagegroup-firmware-qcm6490, -qcom-display/-graphics/
# -video) were the proprietary adreno/PAL stack and are gone with that layer.
# qemu-system-aarch64 (pulls qemu-common) is the aarch64 KVM accelerator's
# userspace. CONFIG_KVM is =y in linux-qcom's qcom.config, and the machine now
# flashes the KVM XBL config (see avocado-rubikpi3.conf), so /dev/kvm is usable
# -- but nothing in the feed could open it. Feed-only like everything else here;
# the BSP extension or a user extension installs it. Trimmed to one target arch
# and a headless PACKAGECONFIG in kas/vendor/qcom.yml.
# avocado-bls is feed-only like everything else here; it is what clears
# systemd-boot's boot-assessment counter after a good boot, from the stone
# manifest's update.commit actions, and every board on this SoC boots the same
# way. Named here rather than in MACHINE_ESSENTIAL_EXTRA_RDEPENDS because that
# variable feeds packagegroup-core-boot, a *Yocto image* concept: avocado's
# runtime rootfs is assembled by avocado-cli from its own package list, so a
# recipe named only there is never built into the feed and never installed.
RDEPENDS:${PN}:append:qcm6490 = " \
    avocado-bls \
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
    qemu-system-aarch64 \
"
# wireless-regdb-static is here for the same reason the other machine-extra
# packagegroups carry it (compulab, variscite, stm): it comes from
# packagegroup-avocado-feature-networking, which the per-machine feed build does
# not pull, so the package never reaches the feed and the BSP extension's
# `ext install` fails with "No match for argument: wireless-regdb-static" even
# though a local avocado-complete build produces it. brcmfmac needs the
# regulatory database; see the note in firmware-rubikpi3_1.0.bb.
# systemd-rubikpi3-masks masks units that do not apply on this board
# (boot.mount/boot.automount, systemd-boot-*, proc-fs-nfsd.mount) and disables
# OE's getty@ preset, without which the board boots degraded on
# getty@getty.service. It was in the qcm6490 block, which is wrong now that a
# second qcm6490 board exists: the name is rubikpi3's and so are the masks.
RDEPENDS:${PN}:append:rubikpi3 = " \
    systemd-rubikpi3-masks \
    firmware-rubikpi3 \
    linux-firmware-qcom-qcs6490-thundercomm-rubikpi3-audio \
    rubikpi-bt-staticdev \
    rubikpi-wifi \
    rubikpi3-init-services-bt \
    rubikpi3-init-services-wifi \
    rubikpi3-thermal \
    wireless-regdb-static \
    wiringrp \
    wiringrp-gpio \
    wiringrp-python \
"

# RB3 Gen 2 peripherals that are not SoC-level.
#
# qps615-dlkm is the board's ETHERNET. The RB3 Gen 2 puts its NIC behind a
# QPS615 PCIe switch, driven by an out-of-tree module (a Qualcomm fork of
# Toshiba's TC956x driver) plus a firmware blob the bridge loads at probe. Both
# are public. Named here because a board that boots without a NIC is the exact
# failure this layer already paid for once on rubikpi3: with the module absent
# nothing about the build fails, and the device simply comes up with no network.
#
# The module inherits `module`, so it builds against virtual/kernel and is
# produced once per multiconfig -- one build for the stock kernel and one for
# PREEMPT_RT, renamed per KERNEL_VERSION by avocado-multikernel.bbclass, the
# same way kernel-modules already are.
#
# Wifi and Bluetooth are WCN6750 on this board, not the part the qcm6490 block's
# firmware covers.
#
# Deliberately NOT here: the Hexagon DSP binaries, the QAIRT SDK and
# camxfirmware-kodiak. Those are the compute and camera stacks, they are large,
# and the camera path on an upstream kernel needs CamX -- which is the harder
# half of Vision Kit support and is not attempted by naming a firmware package.
RDEPENDS:${PN}:append:rb3gen2 = " \
    qps615-dlkm \
    qps615-firmware \
    linux-firmware-ath11k-wcn6750 \
    linux-firmware-qca-wcn6750 \
    linux-firmware-lt9611uxc \
    linux-firmware-qcom-qcs6490-modem \
"
