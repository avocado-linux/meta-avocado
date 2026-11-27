DESCRIPTION = "Packagegroup for inclusion in extra Avocado tegra images"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

# Every name here must be a package the feed carries, or dnf cannot install
# the group. tegra-binaries only unpacks the BSP for other recipes and ships
# no package. kernel-module-r8168 is left out too: NVIDIA's OOT tree builds
# r8168 only for its 5.15 kernel, so nothing provides it with linux-yocto
# (whose in-tree r8169 drives the same NICs), and a kernel's modules belong in
# that kernel's own module groups, not in a group shared by every kernel.
RDEPENDS:${PN} = " \
  deepstream-7.1-pyds \
  deepstream-7.1 \
  python3-tensorrt \
  tegra-firmware \
  tegra-redundant-boot-base \
  tegra-nvphs \
  tegra-nvs-service \
  tegra-nvsciipc \
  tegra-nvstartup \
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
  tensorrt-samples \
  tensorrt-trtexec \
  tensorrt-trtexec-prebuilt \
  nvidia-docker \
  linux-firmware-rtl8168 \
  ${GSTREAMER_PACKAGES} \
  swupdate \
  avocado-boot-device \
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
