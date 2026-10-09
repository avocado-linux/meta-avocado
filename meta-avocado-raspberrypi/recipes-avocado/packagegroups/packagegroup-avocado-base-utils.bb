DESCRIPTION = "GNU base utilities for Avocado images that ship without BusyBox"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"

inherit packagegroup nospdx

# packagegroup-core-base-utils also pulls wget, bind-utils, inetutils and
# dhcpcd. This feed does not build those today (wget fails do_package_qa on a
# TMPDIR reference) and a systemd-networkd image does not need them, so the
# set is spelled out here. oe-core splits iproute2 per tool and the iproute2
# package ships only `ip`, so `ss` is listed on its own: without BusyBox there
# is no netstat, and ss is the socket listing left.
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
  iproute2-ss \
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
