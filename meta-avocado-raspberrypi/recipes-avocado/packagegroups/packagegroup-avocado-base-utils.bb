DESCRIPTION = "GNU base utilities for Avocado images that ship without BusyBox"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"

inherit packagegroup nospdx

# packagegroup-core-base-utils also pulls wget, bind-utils, inetutils and
# dhcpcd. This feed does not build those today (wget fails do_package_qa on a
# TMPDIR reference) and a systemd-networkd image does not need them, so the
# set is spelled out here.
RDEPENDS:${PN} = " \
  bash \
  bzip2 \
  coreutils \
  cpio \
  diffutils \
  e2fsprogs \
  file \
  findutils \
  gawk \
  grep \
  gzip \
  iproute2 \
  iputils-ping \
  kmod \
  less \
  patch \
  procps \
  psmisc \
  sed \
  shadow-base \
  tar \
  util-linux \
  which \
  xz \
"
