DESCRIPTION = "Packagegroup for extra inclusions in Avocado Rockchip images"
LICENSE = "Apache-2.0"

inherit features_check

IMAGE_FEATURES += ""
REQUIRED_DISTRO_FEATURES = ""

# RDEPENDS pulls in ${MACHINE_EXTRA_RRECOMMENDS}, which differs per rockchip
# machine (rock-5b vs orangepi-5-plus, etc.). Keeping this noarch makes the
# same packagegroup RPM diverge per build and trip Pulp dedupe on upload. Set
# PACKAGE_ARCH before `inherit packagegroup` so packagegroup.bbclass skips its
# conditional `inherit_defer allarch`.
PACKAGE_ARCH = "${MACHINE_ARCH}"

inherit packagegroup

RDEPENDS:${PN} = " \
  ${MACHINE_EXTRA_RRECOMMENDS} \
"
