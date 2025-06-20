DESCRIPTION = "Packagegroup for inclusion in extra Avocado tegra images"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup

DEPENDS = "nvidia-kernel-oot"

RDEPENDS:${PN} = " \
  tensorrt-trtexec \
  triton-server \
  triton-client \
  triton-python-backend \
  triton-tensorrt-backend \
  triton-onnxruntime-backend \
  tegra-mmapi \
  tegra-libraries-gbm-backend \
  tegra-libraries-multimedia-utils \
  libglvnd \
  egl-gbm \
  weston \
  weston-init \
  wayland \
  l4t-graphics-demos-wayland \
  weston-examples \
  cuda-libraries \
  xserver-xorg-video-nvidia \
  deepstream-7.1 \
"
