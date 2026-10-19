DESCRIPTION = "Installs the GNU versions of the BusyBox applets; meant for an extension"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"

inherit packagegroup nospdx

# Meant for an extension. The base rootfs keeps BusyBox for the applets it does
# not already replace; an extension that wants GNU behavior lists this one
# package, and the update-alternatives links of the packages below (ip, ps,
# grep, awk and the like) land in the extension. Packages the base rootfs
# already provides are skipped when the extension is built.
#
# The list is kept in full, including packages the base rootfs already pulls in
# (bash, coreutils, util-linux), so the group stays correct if the base changes.
#
# packagegroup-core-base-utils is not used: it also pulls wget (it fails
# do_package_qa on a TMPDIR reference), bind-utils, inetutils and dhcpcd, none
# of which a systemd-networkd image needs. The set below is what a device needs
# to run services and be debugged over ssh. Build-host tools (patch, diffutils,
# cpio, file, e2fsprogs) are left out: the rootfs is read-only and /var is
# btrfs.
#
# oe-core splits iproute2 per tool and the iproute2 package ships only `ip`.
# iproute2-ss is listed on its own because BusyBox's netstat is not replaced by
# anything else here and `ss` is the socket listing that does the job.
# iproute2-bridge and iproute2-tc are not included; add them where a tool needs
# them.
#
# Not provided by this group: vi, wget, nc, ifconfig, netstat, nslookup. An
# extension that needs them lists them itself.
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
