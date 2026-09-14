SUMMARY = "SDK wrapper that compiles a device-tree overlay source into a .dtbo"
DESCRIPTION = "avocado-cli invokes `avocado-dtc-overlay --name <n> --src <f> \
--out <f>.dtbo` once per overlay declared by an enabled extension. Tooling \
only: dtc plus the wrapper. The dt-bindings headers overlay sources #include \
come from kernel-devsrc in the target-dev sysroot, contributed by whichever \
extension declares the overlays."
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

# The package name is a contract. avocado-cli installs exactly
# `nativesdk-avocado-dtc-overlay` into the SDK when a runtime declares
# device_tree_overlays, and calls exactly `avocado-dtc-overlay`. Without it the
# declaration fails at `avocado sdk install` with "No match for argument", which
# reads as a missing package and means "this BSP has not implemented the SDK
# half of the feature". The target half is avocado-dtc-overlay-deliver.

FILESEXTRAPATHS:prepend := "${THISDIR}/files:"
SRC_URI = "file://avocado-dtc-overlay"

S = "${UNPACKDIR}"

inherit nativesdk

# dtc for the compile, and fdtoverlay for the merge avocado-build-qcom runs
# over what this produces. Both come from the same package.
RDEPENDS:${PN} += "nativesdk-dtc"

# NO kernel dependency here, deliberately.
#
# An earlier revision made this recipe depend on virtual/kernel:do_shared_workdir
# and ship a private copy of include/dt-bindings. That was wrong twice over: it
# coupled a TOOL to a kernel version, so it needed rebuilding on every kernel
# bump; and it baked one kernel's bindings into a package used to compile
# overlays for whichever kernel the PROJECT pinned, so a mismatch would compile
# cleanly and bind the wrong constants.
#
# The kernel is the user's choice (`kernel.version`), so the headers follow that
# choice: an extension declaring overlays also declares an
# `sdk.compile.<name>.packages` section pulling `kernel-devsrc`, which lands in
# the target-dev sysroot at the pinned version. Same mechanism
# ext-kmod-v4l2loopback already uses to build a module against the right kernel.
#
# This package stays tooling: dtc, and the wrapper.

do_configure[noexec] = "1"
do_compile[noexec] = "1"

# ${bindir}, NOT ${SDKPATHNATIVE}${bindir}.
#
# `inherit nativesdk` already re-roots ${bindir} under SDKPATHNATIVE, so
# prefixing it again nests the whole SDK path inside itself: the file landed at
# .../sdk/x86_64/opt/_avocado/<target>/sdk/x86_64/usr/bin/avocado-dtc-overlay
# while PATH holds .../sdk/x86_64/usr/bin. The package installed cleanly and
# the command was still not found, which reads as a packaging or PATH problem
# and is neither. nativesdk-systemd-boot installs ukify the plain way.
do_install() {
    install -Dm 0755 ${S}/avocado-dtc-overlay ${D}${bindir}/avocado-dtc-overlay
}

FILES:${PN} = "${bindir}/avocado-dtc-overlay"

# Headers and a script: nothing to strip, and no ELF to QA.
INHIBIT_PACKAGE_STRIP = "1"
INHIBIT_SYSROOT_STRIP = "1"
