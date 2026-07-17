DESCRIPTION = "Packagegroup for the Avocado system-base feature group"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

RDEPENDS:${PN} = " \
  audit \
  bubblewrap \
  ca-certificates \
  cockpit \
  cockpit-networkmanager \
  cronie \
  coreutils \
  cryptoauthlib \
  curl \
  devmem2 \
  dtc \
  fwup \
  git \
  glibc-utils \
  gnutls \
  gptfdisk \
  htop \
  i2c-tools \
  jq \
  kabtool \
  keyutils \
  less \
  libgpiod \
  libgpiod-tools \
  livebook \
  logrotate \
  lsof \
  ltrace \
  nodejs \
  ${@bb.utils.contains('MACHINE_FEATURES', 'optee', 'optee-client', '', d)} \
  p11-kit \
  parted \
  plymouth \
  procps \
  pstree \
  redis \
  rng-tools \
  rtc-tools \
  rsync \
  screen \
  sscg \
  strace \
  tmux \
  usbip-tools \
  usbutils \
  uv \
  vim \
"
