DESCRIPTION = "Packagegroup for Avocado extra"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

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
  peridiod \
  ${@bb.utils.contains('DISTRO_FEATURES', 'opengl', 'wpewebkit', '', d)} \
  ${MACHINE_EXTRA_RDEPENDS} \
"

RRECOMMENDS:${PN} = " \
  ${MACHINE_EXTRA_RRECOMMENDS} \
"
