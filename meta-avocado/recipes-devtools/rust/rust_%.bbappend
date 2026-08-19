# do_rust_setup_snapshot repoints the prebuilt snapshot's three binaries at the
# uninative loader but sets no rpath, and never touches the libraries beside
# them. Those carry RUNPATH=$ORIGIN/../lib, and libLLVM needs libz.so.1 - which
# the uninative tarball does not ship: uninative-tarball.bb packages glibc,
# patchelf, libxcrypt, libnss-nis and libgcc, nothing more. The uninative loader
# searches RUNPATH and its own sysroot and never the host default paths, so
# rustc cannot start and bootstrap fails on `rustc -vV` returning 127:
#
#   rust-snapshot/bin/rustc: error while loading shared libraries: libz.so.1
#
# zlib-native is already staged in recipe-sysroot-native, so nothing needs
# building - the loader simply has no path to it. Append STAGING_LIBDIR_NATIVE
# after whatever the object already carries so a library the snapshot ships
# still wins over a staged one of the same name. This is the rpath the recipe
# already hands RUST_ALTERNATE_EXE_PATH; the snapshot was the one consumer left
# without it.
#
# Guarded on UNINATIVE_LOADER like the task it extends: without uninative the
# host loader resolves the library and there is nothing to fix.
#
# patchelf is in neither HOSTTOOLS nor HOSTTOOLS_NONFATAL, so it resolves only
# out of recipe-sysroot-native. The recipe this appends to declares that depends
# flag on meta-lts-mixins rust_1.92.0 and oe-core wrynose rust_1.94.1, but not on
# oe-core scarthgap rust_1.75.0, which patches with patchelf-uninative instead.
# Nothing pins PREFERRED_VERSION_rust, and kas/base.yml contemplates dropping the
# mixins layer outright, so re-declare it here rather than inherit it by luck.
do_rust_setup_snapshot[depends] += "patchelf-native:do_populate_sysroot"

do_rust_setup_snapshot:append () {
    if [ ! -z "${UNINATIVE_LOADER}" -a -e "${UNINATIVE_LOADER}" ]; then
        for bin in cargo rustc rustdoc; do
            patchelf ${WORKDIR}/rust-snapshot/bin/$bin \
                --set-rpath \$ORIGIN/../lib:${STAGING_LIBDIR_NATIVE}
        done
        for lib in ${WORKDIR}/rust-snapshot/lib/*.so*; do
            # lib/libLLVM-*.so is a 42-byte ld script rather than an ELF, and
            # patchelf exits non-zero on it. Use patchelf as its own ELF probe so
            # such stubs are skipped without masking a real failure below, and
            # keep what it prints: these objects carry $ORIGIN/../lib, so
            # asserting a bare $ORIGIN would drop an entry rather than add one.
            existing=$(patchelf "$lib" --print-rpath 2>/dev/null) || continue
            if [ -n "$existing" ]; then
                patchelf "$lib" --set-rpath "$existing:${STAGING_LIBDIR_NATIVE}"
            else
                patchelf "$lib" --set-rpath "${STAGING_LIBDIR_NATIVE}"
            fi
        done
    fi
}

# Deliberately limited to bin/ and the top-level lib/. readelf -d on the 1.94.1
# snapshot puts the rest out of reach of this bug rather than out of mind:
#
#   lib/rustlib/*/lib/libstd-*.so  NEEDED is libgcc_s, librt, libpthread, libdl,
#                                  libc, ld-linux - all shipped by uninative.
#   libexec/rust-analyzer-proc-macro-srv
#                                  NEEDED adds librustc_driver, which its own
#                                  $ORIGIN/../lib already resolves to lib/; the
#                                  libz edge is reached through libLLVM's RUNPATH,
#                                  which the loop above fixes.
#   cargo's snapshot               a lone bin/cargo with no *.so* anywhere beside
#                                  it, NEEDED entirely inside uninative's set. So
#                                  do_cargo_setup_snapshot needs no rpath and is
#                                  left alone on purpose, not by omission.

# nativesdk-rust do_install dies at exit 127 running llvm-config:
#
#   recipe-sysroot/opt/_avocado/<machine>/sdk/x86_64/usr/bin/llvm-config:
#     error while loading shared libraries: libzstd.so.1
#
# config.toml carries two llvm-config paths - the build triple points at
# recipe-sysroot-native, the SDK target at recipe-sysroot. For an ordinary
# cross build the target copy is a foreign binary, so bootstrap never
# executes it and the second path is only ever read as configuration. A
# nativesdk SDK built on the same architecture as its host breaks that
# assumption: the binary runs, so bootstrap invokes it for --version, and it
# dies because its libraries live under the SDK prefix inside recipe-sysroot,
# which no RUNPATH covers - readelf -d on that llvm-config shows NEEDED
# entries and no RUNPATH or RPATH at all.
#
# libzstd.so.1 is already staged beside it; nothing needs building. The
# loader simply has no path to it, which is the same shape as the libz gap
# the rust-native snapshot hits above. Point the loader at the sysroot's
# libdir for the task that runs the binary rather than patching a RUNPATH
# into a sysroot artifact, because the binary is correct as shipped - it is
# only ever meant to run from an installed SDK, where its libraries are on
# the default path.
#
# Scoped to class-nativesdk: the native and target variants never hit this,
# since the native llvm-config has its libraries beside it and the target one
# is not executed. Not scoped to a rust version: nothing pins
# PREFERRED_VERSION_rust, so whichever release is current hits the same
# nativesdk llvm-config gap.
do_install:prepend:class-nativesdk() {
    export LD_LIBRARY_PATH="${RECIPE_SYSROOT}${libdir}:${LD_LIBRARY_PATH}"
}
