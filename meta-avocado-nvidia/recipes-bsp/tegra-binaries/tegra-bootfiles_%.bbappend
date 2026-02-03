# SPDX-License-Identifier: MIT
# Install Advantech ICAM-540 custom BPMP firmware, DTB, and BCT files
# These firmware binaries are from the vendor's BSP and contain ODM-specific
# GPIO/pinmux configurations for camera LED control during early boot.

# The fetch task is disabled on this recipe, so we access files directly from the layer.
# Directory where our custom files are stored (resolved at parse time)
ICAM540_FW_DIR := "${THISDIR}/${BPN}/icam-540"

do_install:append:icam-540() {
    # Install Advantech custom BPMP firmware variants
    # TE980M-A1: Orin NX 16GB (SKU D3, D4)
    # TE950M-A1: Orin NX 8GB / Nano (SKU D5, D6)
    install -m 0644 ${ICAM540_FW_DIR}/bpmp_t234-TE980M-A1_prod.bin ${D}${datadir}/tegraflash/
    install -m 0644 ${ICAM540_FW_DIR}/bpmp_t234-TE950M-A1_prod.bin ${D}${datadir}/tegraflash/

    # Install Advantech BPMP DTB
    # This DTB may contain vendor-specific configurations
    install -m 0644 ${ICAM540_FW_DIR}/tegra234-bpmp-3767-0001-3509-a02.dtb ${D}${datadir}/tegraflash/

    # Install Advantech GPIO BCT file
    # This file overrides the default GPIO configuration to set the camera LED
    # control GPIO (H,6) to output-high during early boot, which is required
    # for proper LED behavior on the ICAM-540 carrier board.
    # Key differences from stock meta-tegra:
    #   - GPIO H,6: output-high (vendor) vs output-low (stock)
    #   - GPIO CC,0, CC,2 (AON): input (vendor) vs output-low (stock)
    install -m 0644 ${ICAM540_FW_DIR}/tegra234-mb1-bct-gpio-p3767-hdmi-a03.dtsi ${D}${datadir}/tegraflash/
}
