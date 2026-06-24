DESCRIPTION = "Packagegroup for Avocado extra"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

# SDK target sysroot — target-arch (MACHINE_ARCH) build deps for compiling extensions
# against the target. Moved here from packagegroup-avocado-sdk-extra: the distro build
# builds target-arch (-> target feed), the SDK build builds host/nativesdk (-> sdk feed).
# avocado-sdk-target-sysroot lands in the target feed where the CLI's combined repo conf
# installs it. This is a feed-only packagegroup (via avocado-pkg-extra), so these dev
# packages are installable from the feed but not baked into the rootfs.
SDK_SYSROOT_DEPENDS = " \
  avocado-sdk-target-sysroot \
  kernel-devsrc \
  ${@multilib_pkg_extend(d, 'libstd-rs')} \
  ${@multilib_pkg_extend(d, 'packagegroup-go-sdk-target')} \
"

RDEPENDS:${PN} = " \
  ${SDK_SYSROOT_DEPENDS} \
  audit \
  avahi-daemon \
  avocado-hitl \
  avocado-img-bootfiles \
  avocado-img-initramfs \
  avocado-img-rootfs \
  avocado-img-var \
  avocado-pkg-rootfs \
  avocado-pkg-initramfs \
  bind-utils \
  bubblewrap \
  ca-certificates \
  chrony \
  cifs-utils \
  cockpit \
  cockpit-networkmanager \
  cronie \
  coreutils \
  cryptoauthlib \
  curl \
  devmem2 \
  dnsmasq \
  dtc \
  ${@bb.utils.contains('MACHINE_FEATURES', 'deepx', "${DEEPX_PACKAGES}", '', d)} \
  ethtool \
  fwup \
  git \
  glibc-utils \
  gnutls \
  gptfdisk \
  hostapd \
  htop \
  i2c-tools \
  iperf3 \
  iproute2 \
  iptables \
  jq \
  kabtool \
  keyutils \
  less \
  libgpiod \
  libgpiod-tools \
  libimobiledevice \
  libnss-mdns \
  ${@bb.utils.contains('DISTRO_FEATURES', 'opengl', 'librealsense2', '', d)} \
  libqmi \
  libv4l \
  libwebsockets \
  linux-firmware \
  livebook \
  logrotate \
  lsof \
  ltrace \
  modemmanager \
  mosquitto \
  net-snmp \
  net-tools \
  networkmanager \
  networkmanager-daemon \
  networkmanager-nmcli \
  networkmanager-wwan \
  nodejs \
  ntfs-3g-ntfsprogs \
  opencv \
  openssh \
  openssh-sftp-server \
  openssh-sshd \
  ${@bb.utils.contains('MACHINE_FEATURES', 'optee', 'optee-client', '', d)} \
  p11-kit \
  parted \
  phytool \
  picocom \
  plymouth \
  procps \
  pstree \
  qemu-user-static \
  qemu-user-static-binfmt \
  qemu-guest-agent \
  redis \
  rng-tools \
  rtc-tools \
  rsync \
  screen \
  sscg \
  strace \
  tcpdump \
  tmux \
  tio \
  usbip-tools \
  usbmuxd \
  usbutils \
  uv \
  v4l-utils \
  vim \
  vnstat \
  wireguard-tools \
  wireless-regdb \
  wireless-regdb-static \
  wpa-supplicant \
  zeromq \
  iw \
  bluez5 \
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

DEEPX_PACKAGES = " \
  dx-driver \
  dx-rt \
  dx-stream \
  dx-stream-sample \
"

# AWS Greengrass and openjdk-17 RDEPEND on a JRE/JDK; Amazon Corretto and
# OpenJDK only build for aarch64 and x86_64. Skip on aarch32 (Cortex-A32 /
# Cortex-A7 etc.) where TARGET_ARCH == "arm".
AWS_PACKAGES = "${@' \
  greengrass-bin \
  aws-iot-device-client \
' if d.getVar('TARGET_ARCH') in ('aarch64', 'x86_64') else ''}"

JAVA_PACKAGES = "${@' \
  openjdk-17-jdk \
  openjdk-17-jre \
' if d.getVar('TARGET_ARCH') in ('aarch64', 'x86_64') else ''}"

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
  k3s \
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
  python3-cryptography \
  python3-distro \
  python3-paho-mqtt \
  python3-periphery \
  python3-posix-ipc \
  python3-psutil \
  python3-pycurl \
  python3-pyserial \
  python3-requests \
  python3-smbus2 \
  python3-tzdata \
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
