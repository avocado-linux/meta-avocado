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
  ${DEEPSTREAM_PACKAGES} \
  ${VPI_HPC_PACKAGES} \
  ${DIAGNOSTIC_PACKAGES} \
  ${TEGRA_TEST_PACKAGES} \
  ${SECURITY_PACKAGES} \
  swupdate \
"

# Encrypted-/var + fTPM userspace, published so avocado-cli can install it from
# the single Jetson feed when a runtime opts in (avocado.yaml var.encrypt).
# None of it is in the Yocto rootfs/initramfs images by default.
SECURITY_PACKAGES = " \
  cryptsetup \
  cryptsetup-var \
  cryptsetup-var-udev \
  libdevmapper \
  optee-ftpm-init \
  optee-client \
  tpm2-tools \
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
#   * libcudla -- no recipe present in the wrynose fork.
#   * vkcube -- REQUIRED_DISTRO_FEATURES = "vulkan", which the nvidia vendor
#     config does not set (kas/vendor/nvidia.yml sets only opengl wayland
#     seccomp virtualization efi; synaptics/rubikpi/renesas are the vendors
#     that add vulkan). features_check would SKIP the recipe, and a skipped
#     recipe named here is a hard "Nothing RPROVIDES" failure, not a silent
#     omission. Add ` vulkan` to DISTRO_FEATURES_EXTRA first if wanted.
#   * rendercheck -- DEPENDS on virtual/libx11 libxrender libxext. This is a
#     Wayland image with no x11 DISTRO_FEATURE; it would drag X11 in.
#   * tegra-libraries-vulkan-sc{,-core} / tegra-vulkan-sc-samples -- Vulkan
#     SAFETY CRITICAL, a separate certified driver stack from regular Vulkan.
#     Only relevant to a safety-certified target, and -core is
#     (tegra234|tegra264)-only so it would need the SoC scoping described above.
#   * holoscan-sensor-bridge -- BYOS-over-Ethernet sensor ingest. Plausible
#     (COMPATIBLE_MACHINE "(tegra)", and we already ship holoscan-sdk +
#     gxf-core) but a heavy, narrow dependency set for a use case nobody has
#     asked for yet.
#   * opentelemetry-cpp-1230, yaml-cpp-080-static -- pulled in automatically as
#     RDEPENDS of deepstream-9.1 / holoscan-sdk. Not direct adds.
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

# DeepStream 9.1 (L4T R39.2) inference pipeline + its Python bindings.
#
# Unblocked by the meta-tegra-community f9600de4 update: the 7.1 recipe this
# group used to exclude DEPENDed on libnvvpi3, which the wrynose fork does not
# carry. 9.1 DEPENDS on libnvvpi4 (shipped below in VPI_HPC_PACKAGES), and the
# 7.1 recipe is gone from the layer entirely. Everything else it needs --
# tensorrt-core, tensorrt-plugins, libcufft, libcublas, libnpp -- is already
# here. yaml-cpp-080 and opentelemetry-cpp-1230 arrive as its RDEPENDS.
#
# This is a large source build. It lands in PKG_EXTRA_INSTALL, so it enters the
# feed for every Jetson machine, not just the one being built.
DEEPSTREAM_PACKAGES = " \
  deepstream-9.1 \
  deepstream-9.1-pyds \
"

# VPI (Vision Programming Interface) + multi-GPU/HPC building blocks.
# nvcomp: GPU lossless compression/decompression, COMPATIBLE_MACHINE "(cuda)".
VPI_HPC_PACKAGES = " \
  libnvvpi4 \
  vpi4-samples \
  nccl \
  cutlass \
  matx \
  rmm \
  ucx \
  ucxx \
  nvcomp \
"

# On-device diagnostics / profiling / debug tooling.
# stream (memory bandwidth) and schbench (scheduler latency) are new upstream
# benchmarks -- tiny, no dependencies, no COMPATIBLE_MACHINE restriction.
DIAGNOSTIC_PACKAGES = " \
  python3-jetson-stats \
  nsight-systems \
  cuda-samples \
  cuda-gdb \
  stream \
  schbench \
"

# Tegra self-tests. deepstream-tests was migrated to DeepStream 9.1 upstream,
# so the 7.1 dependency that kept it out of this list no longer exists.
TEGRA_TEST_PACKAGES = " \
  tensorrt-tests \
  vpi-tests \
  tegra-mmapi-tests \
  gstreamer-tests \
  deepstream-tests \
"
