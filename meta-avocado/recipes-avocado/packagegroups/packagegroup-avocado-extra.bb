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
  cockpit \
  dtc \
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
  logrotate \
  coreutils \
  glibc-utils \
  qemu-user-static \
  qemu-user-static-binfmt \
  tio \
  sscg \
  redis \
  net-tools \
  cifs-utils \
  ntfs-3g-ntfsprogs \
  less \
  picocom \
  uv \
  ${GSTREAMER_PACKAGES} \
  ${PYTHON_PACKAGES} \
  ${@bb.utils.contains('DISTRO_FEATURES', 'opengl', "${QT5_PACKAGES}", '', d)} \
  ${@bb.utils.contains('DISTRO_FEATURES', 'opengl', "${BASLER_PACKAGES}", '', d)} \
  ${@bb.utils.contains('DISTRO_FEATURES', 'opengl', "${OPENGL_PACKAGES}", '', d)} \
  ${@bb.utils.contains('DISTRO_FEATURES', 'virtualization', "${CONATINER_PACKAGES}", '', d)} \
  ${JAVA_PACKAGES} \
  ${AWS_PACKAGES} \
  ${@bb.utils.contains('DISTRO_FEATURES', 'opengl wayland', "${BROWSER_PACKAGES}", '', d)} \
"

AWS_PACKAGES = " \
  greengrass-bin \
  aws-iot-device-client \
"

JAVA_PACKAGES = " \
  openjdk-17-jdk \
  openjdk-17-jre \
"

OPENGL_PACKAGES = " \
  wpewebkit \
  wpebackend-fdo \
  cog \
  cage \
  weston \
  weston-init \
  wayland \
  wayland-utils \
  libdrm-tests \
  xkeyboard-config \
"

BROWSER_PACKAGES = " \
  chromium-ozone-wayland \
"

CONATINER_PACKAGES = " \
  docker \
  podman \
  podman-compose \
"

# Basler Pylon SDK is only available for aarch64
BASLER_PACKAGES = "${@' \
  pylon \
  python3-pypylon \
  gst-plugin-pylon \
' if d.getVar('TARGET_ARCH') == 'aarch64' else ''}"

GSTREAMER_PACKAGES = " \
  gstreamer1.0 \
  gstreamer1.0-plugins-base \
  gstreamer1.0-plugins-good \
  gstreamer1.0-plugins-bad \
  gstreamer1.0-plugins-ugly \
  gstreamer1.0-libav \
  mpeg2dec \
"

PYTHON_PACKAGES = " \
  python3-pyyaml \
  python3-pip \
  python3-flask \
  python3-werkzeug \
  python3-jinja2 \
  python3-markupsafe \
  python3-itsdangerous \
  python3-click \
  python3-opencv \
  python3-spidev \
  python3-smbus \
"

QT5_PACKAGES = " \
  qtbase \
  qtbase-plugins \
  qtbase-tools \
  qtdeclarative \
  qtdeclarative-plugins \
  qtdeclarative-tools \
  qtquickcontrols2 \
  qtmultimedia \
  qtmultimedia-plugins \
  qtgraphicaleffects \
  qtsvg \
  qtimageformats \
  qtserialport \
  qtsensors \
  qtconnectivity \
  qtlocation \
  qtnetworkauth \
  qtwebsockets \
  qtwebengine \
  qtxmlpatterns \
  qttools \
  qttools-plugins \
  qtcharts \
  qtvirtualkeyboard \
  qt3d \
  qtgamepad \
  ${@bb.utils.contains('DISTRO_FEATURES', 'opengl wayland', 'qtwayland qtwayland-plugins', '', d)} \
  ${@bb.utils.contains('DISTRO_FEATURES', 'x11', 'qtx11extras', '', d)} \
  ${QT5_OPTIONAL_PACKAGES} \
"

# Optional packages that may require additional dependencies or features
QT5_OPTIONAL_PACKAGES = " \
  ${@bb.utils.contains('DISTRO_FEATURES', 'bluetooth', 'qtconnectivity', '', d)} \
  qtscript \
  qtremoteobjects \
  qtscxml \
  qtdatavis3d \
  qttranslations \
"
