SUMMARY = "Composable device-tree selection: reconcile /etc/avocado/devicetree.d into the u-boot env"
DESCRIPTION = "Ships avocado-devicetree-apply + a oneshot service that merge \
DEVICETREE/OVERLAYS fragments dropped by extensions and configs into the u-boot \
environment (devicetree_file + fdt_overlays), so a base DTB can be stacked with \
.dtbo overlays selected from avocado config. Pairs with the apply_overlays loop \
in the machine u-boot env and KERNEL_DTC_FLAGS=-@ base DTBs."
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

SRC_URI = " \
    file://avocado-devicetree-apply \
    file://avocado-devicetree.service \
"

# file://-only recipe: sources land in UNPACKDIR on wrynose, and the default
# S (${UNPACKDIR}/${BP}) never exists, which do_unpack warns about on every
# build. Point S at where the files actually are, as avocado-users does.
S = "${UNPACKDIR}"

# fw_setenv/fw_printenv at runtime; the env partition wiring is per-machine
# (avocado-uboot-env generates /etc/fw_env.config).
RDEPENDS:${PN} = "libubootenv-bin"

inherit systemd allarch

SYSTEMD_SERVICE:${PN} = "avocado-devicetree.service"

do_install() {
    install -d ${D}${libexecdir}
    install -m 0755 ${UNPACKDIR}/avocado-devicetree-apply ${D}${libexecdir}/avocado-devicetree-apply

    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${UNPACKDIR}/avocado-devicetree.service ${D}${systemd_system_unitdir}/avocado-devicetree.service

    # Drop-in dir extensions/configs write *.conf fragments into.
    install -d ${D}${sysconfdir}/avocado/devicetree.d
}

FILES:${PN} += " \
    ${libexecdir}/avocado-devicetree-apply \
    ${systemd_system_unitdir}/avocado-devicetree.service \
    ${sysconfdir}/avocado/devicetree.d \
"
