DESCRIPTION = "Packagegroup for inclusion in Avocado Rockchip SDKs"
LICENSE = "Apache-2.0"

inherit packagegroup

# nativesdk-rkdeveloptool is added in stage 5 (SDK target extension) once the
# recipe (or class-nativesdk bbappend on meta-rockchip's rkdeveloptool) lands.
RDEPENDS:${PN} = " \
"
