DESCRIPTION = "Avocado feature group: networking daemons and internet tooling"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

RDEPENDS:${PN} = " \
  networkmanager \
  networkmanager-daemon \
  networkmanager-nmcli \
  networkmanager-wwan \
  modemmanager \
  hostapd \
  wpa-supplicant \
  dnsmasq \
  avahi-daemon \
  libnss-mdns \
  chrony \
  openssh \
  openssh-sftp-server \
  openssh-sshd \
  net-snmp \
  net-tools \
  iproute2 \
  iptables \
  ethtool \
  tcpdump \
  iperf3 \
  wireguard-tools \
  mosquitto \
  libwebsockets \
  libqmi \
  bind-utils \
  cifs-utils \
  ntfs-3g-ntfsprogs \
  vnstat \
  picocom \
  tio \
  bluez5 \
  iw \
  wireless-regdb \
  wireless-regdb-static \
  zeromq \
  libimobiledevice \
  usbmuxd \
"
