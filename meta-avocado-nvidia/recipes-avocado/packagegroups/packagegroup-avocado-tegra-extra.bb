DESCRIPTION = "Packagegroup for inclusion in extra Avocado tegra images"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup nospdx
PACKAGES = "${PN}"

RDEPENDS:${PN} = " \
  tegra-firmware \
  tegra-redundant-boot-base \
  tegra-binaries \
  tegra-nvsciipc \
  tegra-nvfancontrol \
  tegra-configs-udev \
  tegra-redundant-boot \
  nvidia-kernel-oot \
  tegra-cuda-utils \
  tegra-tools \
  tegra-libraries-camera \
  tegra-libraries-core \
  tegra-libraries-cuda \
  tegra-libraries-multimedia \
  tegra-libraries-multimedia-ds \
  tegra-libraries-multimedia-v4l \
  tegra-libraries-multimedia-utils \
  tegra-libraries-nvml \
  tegra-libraries-nvsci \
  tegra-libraries-pva \
  tegra-nvpower \
  tegra-mmapi \
  ${GSTREAMER_PACKAGES} \
  ${CONTAINER_PACKAGES} \
  ${TENSORRT_PACKAGES} \
  ${CUDA_MATH_PACKAGES} \
  ${PYTHON_AI_PACKAGES} \
  ${FRAMEWORK_PACKAGES} \
  ${VPI_HPC_PACKAGES} \
  ${DIAGNOSTIC_PACKAGES} \
  ${TEGRA_TEST_PACKAGES} \
  swupdate \
"

GSTREAMER_PACKAGES = " \
  gstreamer1.0-plugins-nvarguscamerasrc \
  gstreamer1.0-plugins-nvcompositor \
  gstreamer1.0-plugins-nvdrmvideosink \
  gstreamer1.0-plugins-nveglgles \
  gstreamer1.0-plugins-nvipcpipeline \
  gstreamer1.0-plugins-nvjpeg \
  gstreamer1.0-plugins-nvtee \
  gstreamer1.0-plugins-nvunixfd \
  gstreamer1.0-plugins-nvv4l2camerasrc \
  gstreamer1.0-plugins-nvvidconv \
  gstreamer1.0-plugins-nvvideo4linux2 \
  gstreamer1.0-plugins-nvvideosinks \
  gstreamer1.0-plugins-tegra \
  nvgstapps \
"

# ---------------------------------------------------------------------------
# NVIDIA "extra goodies" from the upstream meta-tegra / meta-tegra-community
# additions. All entries below are COMPATIBLE_MACHINE-compatible with BOTH
# tegra234 (Orin) and tegra264 (Thor) via the shared (tegra)/(cuda) overrides,
# so they are added unconditionally. If you ever add a SoC-specific recipe,
# scope it with RDEPENDS:${PN}:append:tegra264 / :tegra234 (this group has
# PACKAGE_ARCH = ${MACHINE_ARCH}, so it is rebuilt per machine).
#
# DELIBERATELY EXCLUDED:
#   * deepstream-7.1 / deepstream-7.1-pyds -- DEPENDS on libnvvpi3, which does
#     not exist in the wrynose fork (only libnvvpi4). Adding it makes EVERY
#     tegra rootfs unbuildable. Re-enable only after the recipe is ported to
#     libnvvpi4 (see docs/migrations/scarthgap-to-wrynose.md).
#   * libcudla -- no recipe present in the wrynose fork.
#   * holohub-apps -- Holoscan SAMPLE apps (demo medical-imaging clips), not the
#     framework. Its claraviz volume_renderer links libnvjpeg_static.a, which
#     isn't staged into the sysroot (CUDA static lib in a non-standard
#     /usr/local/cuda path). Upstream is deprecating it: the newest OE4T branch
#     (whinlatter) dropped holohub-apps entirely and JP7.2 (wip-l4t-r39.2.0)
#     pins the older 3.9.0. We keep holoscan-sdk (the framework) + gxf-core.
# ---------------------------------------------------------------------------

# NVIDIA container runtime for Tegra: upstream docker + the `nvidia` runtime
# (JetPack 7 / meta-tegra CSV-passthrough model, NOT x86 CDI). nvidia-container-
# toolkit provides nvidia-ctk + nvidia-container-runtime + the
# nvidia-container-setup.service, and pulls libnvidia-container-tools +
# tegra-configs-container-csv + tegra-container-passthrough. Enables
# `docker run --runtime nvidia <l4t-image>`. (docker-moby itself already comes
# via the virtualization DISTRO feature.) Consumed by the jetson-trt reference's
# docker runtime.
CONTAINER_PACKAGES = " \
  nvidia-container-toolkit \
  libnvidia-container \
"

# TensorRT runtime + Python bindings + trtexec + samples. python3-tensorrt
# pulls tensorrt-core (libnvinfer); the prebuilt trtexec gives a working
# binary without the long samples source build (tensorrt-trtexec, dropped to
# avoid a duplicate-trtexec file conflict -- add it back for scarthgap parity).
TENSORRT_PACKAGES = " \
  tensorrt-core \
  python3-tensorrt \
  tensorrt-plugins-prebuilt \
  tensorrt-trtexec-prebuilt \
  tensorrt-samples \
"

# CUDA-X math libraries + cuDNN (prebuilt binaries; light build cost).
CUDA_MATH_PACKAGES = " \
  cudnn \
  libcublas \
  libcufft \
  libcurand \
  libcusolver \
  libcusparse \
  libnpp \
  libnvjpeg \
"

# Python CUDA/inference stack: CUDA Python bindings + ONNX + ONNX Runtime.
PYTHON_AI_PACKAGES = " \
  python3-cuda \
  python3-pycuda \
  python3-cupy \
  python3-onnx \
  python3-onnxruntime \
"

# Heavy frameworks (large source builds -- hours each). PyTorch/torchvision,
# Triton Inference Server + its TensorRT/ONNXRuntime/Python backends, and the
# Holoscan sensor-processing SDK.
#
# Use the meta-tegra-community (CUDA) builds, NOT the generic meta-python-ai
# ones: python3-torch is the CUDA pytorch_2.11 (meta-python-ai's python3-pytorch
# pulls virtual/libopencl1, which needs the opencl DISTRO feature we don't set),
# and `torchvision` is the CUDA cmake build (meta-python-ai's python3-torchvision
# hard-depends on python3-pytorch -> opencl). See PREFERRED_RPROVIDER for onnx.
FRAMEWORK_PACKAGES = " \
  python3-torch \
  torchvision \
  triton-server \
  triton-core \
  triton-tensorrt-backend \
  triton-onnxruntime-backend \
  triton-python-backend \
  holoscan-sdk \
  gxf-core \
"

# VPI (Vision Programming Interface) + multi-GPU/HPC building blocks.
VPI_HPC_PACKAGES = " \
  libnvvpi4 \
  vpi4-samples \
  nccl \
  cutlass \
  matx \
  rmm \
  ucx \
  ucxx \
"

# On-device diagnostics / profiling / debug tooling.
DIAGNOSTIC_PACKAGES = " \
  python3-jetson-stats \
  nsight-systems \
  cuda-samples \
  cuda-gdb \
"

# Tegra self-tests (deepstream-tests omitted -- it pulls the excluded
# deepstream-7.1 stack above).
TEGRA_TEST_PACKAGES = " \
  tensorrt-tests \
  vpi-tests \
  tegra-mmapi-tests \
  gstreamer-tests \
"
