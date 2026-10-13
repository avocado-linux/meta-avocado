DESCRIPTION = "GNU base utilities for Avocado rootfs images built without BusyBox"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"

inherit packagegroup nospdx

# Selected through kas/feature/gnu-base-utils.yml, which points
# VIRTUAL-RUNTIME_base-utils here.
#
# packagegroup-core-base-utils is not used: it also pulls wget (it fails
# do_package_qa on a TMPDIR reference), bind-utils, inetutils and dhcpcd, none
# of which a systemd-networkd image needs. The set below is what a device needs
# to run services and be debugged over ssh. Build-host tools (patch, diffutils,
# cpio, file, e2fsprogs) are left out: the rootfs is read-only and /var is
# btrfs.
#
# oe-core splits iproute2 per tool and the iproute2 package ships only `ip`.
# iproute2-ss is listed on its own because BusyBox's netstat is gone and `ss`
# is the socket listing that replaces it. iproute2-bridge and iproute2-tc are
# not included; add them where a tool needs them.
#
# Removed with BusyBox, and not replaced here: vi, wget, nc, ifconfig,
# netstat, nslookup. An image that needs them adds them through an extension.
RDEPENDS:${PN} = " \
  bash \
  bzip2 \
  coreutils \
  findutils \
  gawk \
  grep \
  gzip \
  iproute2 \
  iproute2-ss \
  iputils-ping \
  kmod \
  less \
  procps \
  psmisc \
  sed \
  shadow-base \
  tar \
  util-linux \
  which \
  xz \
"
