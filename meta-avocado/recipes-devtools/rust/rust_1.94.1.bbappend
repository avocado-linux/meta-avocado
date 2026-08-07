# nativesdk-rust do_install dies at exit 127 running llvm-config:
#
#   recipe-sysroot/opt/_avocado/<machine>/sdk/x86_64/usr/bin/llvm-config:
#     error while loading shared libraries: libzstd.so.1
#
# config.toml carries two llvm-config paths - the build triple points at
# recipe-sysroot-native (:10), the SDK target at recipe-sysroot (:4). For an
# ordinary cross build the target copy is a foreign binary, so bootstrap never
# executes it and the second path is only ever read as configuration. A
# nativesdk SDK built on the same architecture as its host breaks that
# assumption: the binary runs, so bootstrap's llvm.rs:610 invokes it for
# --version, and it dies because its libraries live under the SDK prefix inside
# recipe-sysroot, which no RUNPATH covers - readelf -d on that llvm-config shows
# NEEDED entries and no RUNPATH or RPATH at all.
#
# libzstd.so.1 is already staged beside it; nothing needs building. The loader
# simply has no path to it, which is the same shape as the libz gap in
# rust-native's snapshot. Point the loader at the sysroot's libdir for the task
# that runs the binary rather than patching a RUNPATH into a sysroot artifact,
# because the binary is correct as shipped - it is only ever meant to run from
# an installed SDK, where its libraries are on the default path.
#
# Scoped to class-nativesdk: the native and target variants never hit this,
# since the native llvm-config has its libraries beside it and the target one is
# not executed.
do_install:prepend:class-nativesdk() {
    export LD_LIBRARY_PATH="${RECIPE_SYSROOT}${libdir}:${LD_LIBRARY_PATH}"
}
