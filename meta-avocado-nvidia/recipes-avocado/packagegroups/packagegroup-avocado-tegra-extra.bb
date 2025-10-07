DESCRIPTION = "Packagegroup for inclusion in extra Avocado tegra images"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

RDEPENDS:${PN} = " \
  tegra-redundant-boot-base \
  tegra-binaries \
  tegra-nvphs \
  tegra-nvs-service \
  tegra-nvsciipc \
  tegra-nvstartup \
  tegra-nvfancontrol \
  tegra-configs-udev \
  tegra-redundant-boot \
  nvidia-kernel-oot-display \
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
  nvidia-docker \
  ${GSTREAMER_PACKAGES} \
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
