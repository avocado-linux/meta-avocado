# Native-exec qemuwrapper for intel-x86-64-v4.
#
# v4 opts qemu-usermode out (avocado-intel-x86-64-v4.conf) because QEMU's TCG
# implements no AVX-512 -- qemu 10.2.0 target/i386/cpu.c has zero AVX-512 bits in
# any TCG_*_FEATURES mask, AVX2 is the ceiling -- and the v4 userland genuinely
# uses it: the built udevadm carries 197 AVX-512 instructions. Emulating a v4
# binary is impossible, not merely slow.
#
# But do_rootfs runs postinst intercepts (update_udev_hwdb, glib's gio module
# cache) by invoking the *target* binary through qemuwrapper, and the stock
# wrapper hard-exits when qemu-usermode is absent. Those postinsts then fall back
# to first boot, which a read-only erofs rootfs cannot honour, so do_rootfs dies:
#
#   ERROR: The following packages could not be configured offline and rootfs is
#   read-only: ['101-libglib-2.0-0', '100-udev-hwdb']
#
# The build host is x86-64 too, so the target binary needs no emulation -- run it
# under the target's own dynamic loader instead. qemu-usermode stays out of
# MACHINE_FEATURES, so meson still gets no exe_wrapper (what the opt-out was for)
# while the intercepts start working.
#
# v2 and v3 are deliberately untouched: SSE4.2 and AVX2 are within TCG's range,
# so their proven qemu path keeps working and this carries no risk for them.
#
# Everything below is scoped to class-target. nativesdk-qemuwrapper-cross runs on
# whatever host the SDK lands on, which need not have AVX-512 -- oe-core exempts
# it from the qemu-usermode guard for the same reason -- so it keeps the stock
# qemu wrapper and skips the build-host check.

FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI:append:intel-x86-64-v4:class-target = " file://qemuwrapper-native"

# Adding a SRC_URI to a recipe that previously fetched nothing makes the
# license-checksum QA check apply, and neither qemuwrapper-cross recipe carries a
# LIC_FILES_CHKSUM (they had nothing to fetch). The wrapper is our own file under
# the recipe's MIT licence, so point at the common MIT text.
LIC_FILES_CHKSUM:intel-x86-64-v4:class-target = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

# Host CPU flags a build host must have for the above to work. Only set for the
# machines that execute target binaries natively; empty elsewhere disables the
# check entirely.
AVOCADO_NATIVE_EXEC_REQUIRES_FLAGS ?= ""
AVOCADO_NATIVE_EXEC_REQUIRES_FLAGS:intel-x86-64-v4:class-target = "avx512f avx512bw avx512cd avx512dq avx512vl"

# Fail at parse, not two hours later inside do_rootfs. Without this the build
# runs to ~95% and then dies on a SIGILL or an offline-postinst error whose text
# says nothing about the host CPU.
python () {
    required = (d.getVar('AVOCADO_NATIVE_EXEC_REQUIRES_FLAGS') or '').split()
    if not required:
        return

    try:
        with open('/proc/cpuinfo') as f:
            cpuinfo = f.read()
    except OSError as e:
        bb.fatal("avocado-x86-64: cannot read /proc/cpuinfo to verify this build "
                 "host can execute %s binaries natively: %s" % (d.getVar('MACHINE'), e))

    flags = set()
    for line in cpuinfo.splitlines():
        if line.startswith('flags'):
            flags = set(line.split(':', 1)[1].split())
            break

    missing = [f for f in required if f not in flags]
    if missing:
        bb.fatal(
            "%s cannot be built on this host.\n"
            "\n"
            "Missing CPU feature(s): %s\n"
            "\n"
            "This target compiles to x86-64-v4, whose binaries use AVX-512. They are\n"
            "run during do_rootfs (udev hwdb, glib schema cache) and QEMU's TCG cannot\n"
            "emulate AVX-512, so they are executed directly on the build host instead.\n"
            "That requires a host CPU implementing the full v4 feature set.\n"
            "\n"
            "Build %s on an AVX-512 host (Intel Skylake-SP and later Xeon, AMD Zen 4\n"
            "and later). x86-64-v2 and x86-64-v3 have no such requirement and build\n"
            "anywhere."
            % (d.getVar('MACHINE'), ' '.join(missing), d.getVar('MACHINE')))
}

do_install:append:intel-x86-64-v4:class-target() {
    install -m 0755 ${UNPACKDIR}/qemuwrapper-native \
        ${D}${bindir_crossscripts}/${MLPREFIX}qemuwrapper
}
