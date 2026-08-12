DESCRIPTION = "Packagegroup for the i.MX NPU / eIQ ML stack in the Avocado feed"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

# Each i.MX NPU family carries its own TFLite delegate stack; the right one is
# selected by MACHINE override so this single packagegroup stays safe to wire
# into the shared NXP PKG_EXTRA_INSTALL (empty on machines with no NPU).
#
#   mx8mp-nxp-bsp -- Vivante VIP9000: VX delegate. tim-vx / tflite-vx-delegate
#       are version-matched to NXP's imx-gpu-viv 6.4.11 (libOpenVX/libVSC) +
#       galcore, COMPATIBLE only on mx8-nxp-bsp + imxgpu3d (e.g. imx8mp-evk,
#       ucm-imx8m-plus). The NN/OpenVX userspace arrives with imx-gpu-viv.
#
#   mx93-nxp-bsp -- Arm Ethos-U65 microNPU: Ethos-U delegate. Models are
#       offline-compiled by Vela (ethos-u-vela; run in the SDK, not shipped)
#       into an Ethos-U command stream; tflite-ethosu-delegate + the driver
#       stack run them, and ethos-u-firmware feeds the microNPU. All four
#       recipes are COMPATIBLE_MACHINE = "(mx93-nxp-bsp)".
#
# Neutron (mx95) would add its own NPU_ML_PKGS:mx95-nxp-bsp branch here.
NPU_ML_PKGS = ""
NPU_ML_PKGS:mx8mp-nxp-bsp = " \
    tensorflow-lite \
    tensorflow-lite-vx-delegate \
    tim-vx \
    nnstreamer \
    nnstreamer-tensorflow-lite \
    nnstreamer-python3 \
"
NPU_ML_PKGS:mx93-nxp-bsp = " \
    tensorflow-lite \
    tensorflow-lite-ethosu-delegate \
    ethos-u-driver-stack \
    ethos-u-firmware \
    nnstreamer \
    nnstreamer-tensorflow-lite \
    nnstreamer-python3 \
"

# nnshark (GStreamer NN profiler) is intentionally omitted: it DEPENDS on
# libgpuperfcnt, which lives in meta-imx-sdk -- a meta-imx sublayer Avocado does
# not vendor (we pull only meta-imx-bsp / -ml / -v2x). It's an optional profiling
# overlay, not part of the inference path. Add it (and vendor meta-imx-sdk) only
# if GPU/NPU perf-counter profiling is specifically wanted.

ALLOW_EMPTY:${PN} = "1"
RDEPENDS:${PN} = "${NPU_ML_PKGS}"
