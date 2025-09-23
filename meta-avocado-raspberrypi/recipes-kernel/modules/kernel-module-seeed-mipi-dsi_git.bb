FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

# Basic description
DESCRIPTION = "Custom Device Tree and Kernel Modules for Seeed ReTerminal"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

DEPENDS += "virtual/kernel dtc-native"

# Specify compatible machine(s)
COMPATIBLE_MACHINE = "avocado-reterminal|avocado-reterminal-dm"

SRCREV = "e9d88ebad195561a0b788d36f59bc67a7bcc697b"

SRC_URI = "\
    https://raw.githubusercontent.com/Seeed-Studio/seeed-linux-dtoverlays/${SRCREV}/modules/mipi_dsi/mipi_dsi_drv.c;name=mipi_dsi_drv \
    https://raw.githubusercontent.com/Seeed-Studio/seeed-linux-dtoverlays/${SRCREV}/modules/mipi_dsi/panel-ili9881x.c;name=ili9881x \
    https://raw.githubusercontent.com/Seeed-Studio/seeed-linux-dtoverlays/${SRCREV}/modules/mipi_dsi/touch_panel.c;name=touch_panel \
    https://raw.githubusercontent.com/Seeed-Studio/seeed-linux-dtoverlays/${SRCREV}/modules/mipi_dsi/mipi_dsi.h;name=mipi_dsi \
    file://Makefile \
    file://0001-Fix-drm-warnings-for-panel-rotation.patch \
"

SRC_URI[mipi_dsi_drv.sha256sum] = "23ddf55f4a3d542dce3b0af96a3062366a9389d566914a976bb973ef2849e510"
SRC_URI[ili9881x.sha256sum] = "eeae8750f2bf1ba4da56da00eff431f4bd87bd571fff5bfdae67ce4b78d40c65"
SRC_URI[touch_panel.sha256sum] = "01adf23cfae63b9cdd8467db7e37ba6d35069cd7cf60586cf9a5abe488631d33"
SRC_URI[mipi_dsi.sha256sum] = "676a441e0d937a0c8c3d2f91519b20b86e3a2262fb8a039645f844484774a183"

S = "${WORKDIR}"

inherit module

# Add the module to the package
RPROVIDES:${PN} += "kernel-module-seeed-mipi-dsi"
