DESCRIPTION = "Packagegroup for the i.MX NPU / eIQ ML stack in the Avocado feed"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

# The NPU userspace, per SoC. The accelerator differs by part, so the delegate
# does too, and naming the wrong one is a runtime fallback to CPU rather than a
# build error -- hence the explicit per-override lists and an empty default.
#
# Both stacks need meta-imx-ml (the i.MX deltas) AND meta-freescale-ml (the base
# recipes NXP moved out in meta-imx e6e7f71d02); see kas/vendor/nxp.yml.
NPU_ML_PKGS = ""

# i.MX8M Plus: Vivante VIP9000, reached through tim-vx and the TFLite VX
# delegate. Version-matched to NXP's imx-gpu-viv (libOpenVX/libVSC) + galcore,
# which arrive with the GPU stack.
NPU_ML_PKGS:mx8mp-nxp-bsp = " \
  tensorflow-lite \
  tensorflow-lite-vx-delegate \
  tim-vx \
  nnstreamer \
  nnstreamer-tensorflow-lite \
  nnstreamer-python3 \
"

# i.MX95: eIQ Neutron, reached through the TFLite Neutron delegate. `neutron`
# is the driver userspace (libNeutronDriver.so) behind it; the kernel side is
# the imx95-neutron remoteproc, already in the device tree.
#
# litert + litert-neutron-delegate (the newer LiteRT generation, also present on
# Variscite's reference image) are deliberately left out: litert_2.1.0 DEPENDS
# on virtual/libopencl1, which on i.MX comes from imx-gpu-viv and is therefore
# Vivante-only -- i.MX95 has a Mali GPU. The other provider, opencl-icd-loader,
# lives in meta-imx-sdk, a meta-imx sublayer Avocado does not vendor. Adding
# LiteRT means vendoring that sublayer first; the TFLite delegate is what the
# nnstreamer inference path uses either way.
#
# A model must be compiled for Neutron offline (NXP's neutron-converter) after
# INT8 quantization -- the delegate does not JIT an unconverted .tflite, it
# silently falls back to CPU.
NPU_ML_PKGS:mx95-nxp-bsp = " \
  neutron \
  tensorflow-lite \
  tensorflow-lite-neutron-delegate \
  nnstreamer \
  nnstreamer-tensorflow-lite \
  nnstreamer-python3 \
"

# nnshark (GStreamer NN profiler) is intentionally omitted: it DEPENDS on
# libgpuperfcnt, which lives in meta-imx-sdk -- a meta-imx sublayer Avocado does
# not vendor. It is an optional profiling overlay, not part of the inference
# path.

ALLOW_EMPTY:${PN} = "1"
RDEPENDS:${PN} = "${NPU_ML_PKGS}"
