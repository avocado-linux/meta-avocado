SUMMARY = "NVIDIA (Tegra) device-tree overlay delivery hook for the Avocado CLI"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

# The package name is a contract: avocado-cli installs exactly
# `avocado-dtc-overlay-deliver` into the target sysroot when a runtime declares
# overlays and runs ${OECORE_TARGET_SYSROOT}/usr/libexec/avocado/device-tree-overlay-deliver.
# Each BSP layer ships its own implementation under that one name.

# Orin (tegra234) only. On Thor, initrd-flash.sh retargets DTBFILE at the module
# SKU it reads off the board at flash time (retarget_module_sku_t264), so a tree
# merged at build time into the BSP's DTBFILE is not necessarily the tree that
# gets flashed: the board would boot without the overlays and report nothing.
COMPATIBLE_MACHINE = "(tegra234)"

SRC_URI = " \
    file://device-tree-overlay-deliver \
    file://boot-settings.json \
"

S = "${UNPACKDIR}"

inherit allarch

INHIBIT_DEFAULT_DEPS = "1"
do_configure[noexec] = "1"
do_compile[noexec] = "1"

# The CLI runs this at build time from the target sysroot, under the SDK's
# python3 (resolved via PATH in the SDK container), so it is a pure script with
# no on-device python3 runtime dependency. Unlike the Raspberry Pi hook, it
# shells out to fdtoverlay to merge the overlays into the base DTB; fdtoverlay
# ships with nativesdk-dtc, which avocado-sdk-target already carries.
#
# boot-settings.json tells the CLI which kinds of boot setting this board
# delivers, so a project that declares one it cannot gets a build failure that
# names the kind. This hook merges compiled overlays only (a stock overlay is
# never staged, and boot_config is never read); kernel_args is applied by
# avocado-tegra-bootimg when the build hook repacks boot.img, which is why it
# is listed even though this hook does not touch it. The test in tests/ checks
# the file against what the hook does.
do_install() {
    install -d ${D}${libexecdir}/avocado
    install -m 0755 ${S}/device-tree-overlay-deliver \
        ${D}${libexecdir}/avocado/device-tree-overlay-deliver
    install -m 0644 ${S}/boot-settings.json \
        ${D}${libexecdir}/avocado/boot-settings.json
}

FILES:${PN} += " \
    ${libexecdir}/avocado/device-tree-overlay-deliver \
    ${libexecdir}/avocado/boot-settings.json \
"
