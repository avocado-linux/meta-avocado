DESCRIPTION = "NVIDIA (Tegra) device-tree overlay delivery hook for the Avocado CLI"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

SRC_URI = " \
    file://device-tree-overlay-deliver \
"

inherit allarch

# The CLI runs this at build time from the target sysroot, under the SDK's
# python3 (resolved via PATH in the SDK container), so it is a pure script with
# no on-device python3 runtime dependency.
#
# Unlike the Raspberry Pi hook, this one shells out to fdtoverlay to merge the
# overlays into the base DTB. fdtoverlay ships with dtc, which the SDK already
# carries to compile .dtso in the avocado-dtc-overlay step that runs
# immediately before this hook.
do_install() {
    install -d ${D}${libexecdir}/avocado
    install -m 0755 ${WORKDIR}/device-tree-overlay-deliver \
        ${D}${libexecdir}/avocado/device-tree-overlay-deliver
}

FILES:${PN} += " \
    ${libexecdir}/avocado/device-tree-overlay-deliver \
"
