DESCRIPTION = "Packagegroup for the i.MX NPU / eIQ ML stack in the Avocado feed"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

# Only the i.MX8M Plus (Vivante VIP9000 NPU) gets the VX-delegate eIQ stack.
# tim-vx / tflite-vx-delegate are version-matched to NXP's imx-gpu-viv 6.4.11
# (libOpenVX/libVSC) + galcore, and are COMPATIBLE only on mx8-nxp-bsp +
# imxgpu3d -- which the NXP-BSP i.MX8MP boards (e.g. ucm-imx8m-plus) carry.
# Empty on every other machine so this is safe to wire into the shared NXP
# PKG_EXTRA_INSTALL. Other NPUs (Ethos-U on mx93, Neutron on mx95) use
# different delegates and would get their own packagegroup. The NN/OpenVX
# userspace itself arrives with imx-gpu-viv (already built for the GPU).
NPU_ML_PKGS = ""
NPU_ML_PKGS:mx8mp-nxp-bsp = " \
    tensorflow-lite \
    tensorflow-lite-vx-delegate \
    tim-vx \
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
