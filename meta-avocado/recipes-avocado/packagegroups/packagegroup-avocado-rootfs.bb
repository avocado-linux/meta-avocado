DESCRIPTION = "Packagegroup for inclusion in  Avocado image"
LICENSE = "Apache-2.0"

inherit packagegroup

RDEPENDS:${PN} = " \
  packagegroup-core-boot \
  base-files \
  base-passwd \
  netbase \
  btrfs-tools \
  ${VIRTUAL-RUNTIME_base-utils} \
  ${VIRTUAL-RUNTIME_login_manager} \
  ${MACHINE_ESSENTIAL_EXTRA_RDEPENDS} \
"

RRECOMMENDS:${PN} = "\
  ${VIRTUAL-RUNTIME_base-utils-syslog} \
  ${MACHINE_ESSENTIAL_EXTRA_RRECOMMENDS} \
"
