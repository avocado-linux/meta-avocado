SUMMARY = "NXP i.MX (loose-file U-Boot boot) device-tree overlay delivery hook for the Avocado CLI"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

# The package name is a contract: avocado-cli installs exactly
# `avocado-dtc-overlay-deliver` into the target sysroot when a runtime declares
# overlays and runs ${OECORE_TARGET_SYSROOT}/usr/libexec/avocado/device-tree-overlay-deliver.
# Each BSP layer ships its own implementation under that one name.

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
# no on-device python3 runtime dependency.
#
# boot-settings.json tells the CLI which kinds of boot setting this board
# delivers, so a project that declares one it cannot gets a build failure that
# names the kind. Keep it in step with what the hook claims; the test in tests/
# checks that every kind listed is claimed.
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
