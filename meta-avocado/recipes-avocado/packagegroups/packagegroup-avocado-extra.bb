DESCRIPTION = "Packagegroup for Avocado extra"
LICENSE = "Apache-2.0"

inherit packagegroup
PACKAGE_ARCH = "${MACHINE_ARCH}"

RDEPENDS:${PN} = " \
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
"
