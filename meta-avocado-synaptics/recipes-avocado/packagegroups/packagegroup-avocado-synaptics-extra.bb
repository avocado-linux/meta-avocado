DESCRIPTION = "Packagegroup for extra inclusions in Avocado Synaptics images"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup nospdx

require recipes-bsp/images/astra-media-common-ips.inc

# Reset PACKAGES to only the packagegroup itself; the inc file's PACKAGES =+
# is intended for image recipes and is not applicable here.
PACKAGES = "${PN}"

RDEPENDS:${PN} = " \
    ${MACHINE_EXTRA_RRECOMMENDS} \
    ${GST_PACKAGES} \
    ${GPU_RELATED_PACKAGES} \
    ${@bb.utils.contains('SYNA_NPU_ENABLE', '1', '${TORQ_PACKAGES} ${NPU_RELATED_PACKAGES}', '', d)} \
"
