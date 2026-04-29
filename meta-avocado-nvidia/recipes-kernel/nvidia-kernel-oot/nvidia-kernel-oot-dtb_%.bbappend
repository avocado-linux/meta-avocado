FILESEXTRAPATHS:prepend := "${THISDIR}/files:"
FILESEXTRAPATHS:prepend:icam-540 := "${THISDIR}/files/icam-540:"

# icam-540: Custom DTB and overlay DTBOs from Advantech BSP
# Uses the -nv (NVIDIA camera-enabled) kernel DTB as verified from manufacturer's flash log
SRC_URI:append:icam-540 = " \
    file://tegra234-p3768-0000+p3767-0001-nv.dtb \
    file://tegra234-p3768-0000+p3767-0000-dynamic.dtbo \
    file://tegra234-dcb-p3767-0000-hdmi.dtbo \
"

do_deploy:append:icam-540() {
    # Install custom DTB and DTBOs directly to deploy directory
    # This runs after the main do_deploy, so these files override the upstream versions
    # Note: Install with the base name expected by KERNEL_DEVICETREE (without -nv suffix)
    # but use the -nv content which has proper CSI/NVCSI camera configuration
    install -m 0644 ${UNPACKDIR}/tegra234-p3768-0000+p3767-0001-nv.dtb ${DEPLOYDIR}/devicetree/tegra234-p3768-0000+p3767-0001-nv.dtb
    # Install overlay DTBOs (overrides upstream with ICAM-540 specific versions)
    install -m 0644 ${UNPACKDIR}/tegra234-p3768-0000+p3767-0000-dynamic.dtbo ${DEPLOYDIR}/devicetree/
    install -m 0644 ${UNPACKDIR}/tegra234-dcb-p3767-0000-hdmi.dtbo ${DEPLOYDIR}/devicetree/
}
