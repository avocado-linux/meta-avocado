SUMMARY = "Device-tree overlay delivery hook for the Qualcomm flow"
DESCRIPTION = "The per-BSP hook avocado-cli invokes when an enabled extension \
declares `device_tree_overlays`. On this platform the device tree is embedded \
in the UKI, so delivery means getting the overlays into the tree the UKI \
carries: this hook validates and claims what the CLI staged, and \
avocado-build-qcom merges them when it rebuilds the UKI."
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

# The package name is a contract, not a choice. avocado-cli installs exactly
# `avocado-dtc-overlay-deliver` into the target sysroot when a runtime declares
# overlays, and runs exactly
# ${OECORE_TARGET_SYSROOT}/usr/libexec/avocado/device-tree-overlay-deliver --
# it never scans a directory. Each BSP layer ships its own implementation under
# that one name, and because only one BSP's layers are present in a machine
# build, exactly one is ever installed.
#
# Until this existed, declaring device_tree_overlays on a qcom target failed at
# `avocado install` with "No match for argument: avocado-dtc-overlay-deliver",
# which reads as a missing package and is really "this BSP has not implemented
# its half of the feature".

COMPATIBLE_MACHINE = "(rubikpi3|rb3gen2|q911)"

FILESEXTRAPATHS:prepend := "${THISDIR}/files:"
SRC_URI = " \
    file://device-tree-overlay-deliver \
    file://boot-settings.json \
"

S = "${UNPACKDIR}"

INHIBIT_DEFAULT_DEPS = "1"
do_configure[noexec] = "1"
do_compile[noexec] = "1"

# allarch because the payload is a shell script. That is not incidental: the
# hook is installed into the TARGET sysroot but EXECUTED on the build host, in
# the SDK container, so anything architecture-specific here would be an aarch64
# binary that cannot run. Keeping it a script is what lets a target package be
# invoked by the build.
inherit allarch

# No RDEPENDS on python3-core.
#
# The validate/claim pass runs `python3`, but it resolves out of the SDK
# container's PATH -- the nativesdk interpreter -- not from this sysroot.
# Depending on the target python3 would drag an aarch64 interpreter into the
# target sysroot that nothing can execute and nothing would use.

# boot-settings.json tells the CLI which kinds of boot setting this board
# delivers, so a project that declares one it cannot gets a build failure that
# names the kind, before anything is compiled. This hook takes compiled overlays
# only (a stock overlay is never staged, and boot_config is never read), and
# kernel_args is applied by avocado-build-qcom, which is why it is listed even
# though this hook does not touch it. The test in tests/ checks the file against
# what the hook does.
do_install() {
    install -d ${D}${libexecdir}/avocado
    install -m 0755 ${S}/device-tree-overlay-deliver \
        ${D}${libexecdir}/avocado/device-tree-overlay-deliver
    install -m 0644 ${S}/boot-settings.json \
        ${D}${libexecdir}/avocado/boot-settings.json
}

FILES:${PN} = " \
    ${libexecdir}/avocado/device-tree-overlay-deliver \
    ${libexecdir}/avocado/boot-settings.json \
"

# Nothing else RDEPENDS on this; the CLI installs it by name into the target
# sysroot when it is needed, so it must exist in the feed whether or not any
# image pulls it in.
BBCLASSEXTEND = ""
