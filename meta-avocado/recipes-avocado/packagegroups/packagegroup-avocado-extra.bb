DESCRIPTION = "Packagegroup for Avocado extra"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

XSERVER ?= "xserver-xorg \
            xf86-video-fbdev \
            xf86-video-modesetting \
            "
XSERVERCODECS ?= ""

RDEPENDS:${PN} = " \
  openssh \
  openssh-sshd \
  openssh-sftp-server \
  vim \
  strace \
  lsof \
  ldd \
  civetweb \
  procps \
  tcpdump \
  pstree \
  ltrace \
  iproute2 \
  htop \
  cryptoauthlib \
  peridiod \
  ganesha \
  nfs-utils \
  ${XSERVER} \
  ${XSERVERCODECS} \
  ${@bb.utils.contains('DISTRO_FEATURES', 'opengl', 'wpewebkit', '', d)} \
  ${MACHINE_EXTRA_RDEPENDS} \
"

RRECOMMENDS:${PN} = " \
  ${MACHINE_EXTRA_RRECOMMENDS} \
"
