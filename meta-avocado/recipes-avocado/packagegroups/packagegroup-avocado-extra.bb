DESCRIPTION = "Packagegroup for Avocado extra"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

RDEPENDS:${PN} = " \
  avocado-hitl \
  avocado-img-bootfiles \
  avocado-img-initramfs \
  avocado-img-rootfs \
  avocado-img-var \
  avocado-pkg-rootfs \
  openssh \
  openssh-sshd \
  openssh-sftp-server \
  vim \
  strace \
  lsof \
  procps \
  tcpdump \
  pstree \
  ltrace \
  iproute2 \
  htop \
  cryptoauthlib \
  peridiod \
  fwup \
  parted \
  rsync \
  avahi-daemon \
  libnss-mdns \
  i2c-tools \
  iperf3 \
  p11-kit \
  ca-certificates \
  ethtool \
  livebook \
  v4l-utils \
  libv4l \
  nodejs \
  opencv \
  usbutils \
  libgpiod \
  libgpiod-tools \
  ${BASLER_PACKAGES} \
  ${GSTREAMER_PACKAGES} \
  ${@bb.utils.contains('DISTRO_FEATURES', 'opengl', "${OPENGL_PACKAGES}", '', d)} \
  ${@bb.utils.contains('DISTRO_FEATURES', 'virtualization', "${CONATINER_PACKAGES}", '', d)} \
"

OPENGL_PACKAGES = " \
  wpewebkit \
  wpebackend-fdo \
  cog \
  weston \
  weston-init \
  wayland \
  wayland-utils \
  libdrm-tests \
"

CONATINER_PACKAGES = " \
  docker \
  podman \
  podman-compose \
"

BASLER_PACKAGES = " \
  pylon \
  python3-pypylon \
  gst-plugin-pylon \
"
GSTREAMER_PACKAGES = " \
  gstreamer1.0 \
  gstreamer1.0-plugins-base \
  gstreamer1.0-plugins-good \
  gstreamer1.0-plugins-bad \
  gstreamer1.0-plugins-ugly \
  mpeg2dec \
"
