# do_rust_setup_snapshot repoints the prebuilt snapshot's three binaries at the
# uninative loader but sets no rpath, and never touches the libraries beside
# them. Those carry RUNPATH=$ORIGIN, and libLLVM needs libz.so.1 - which the
# uninative tarball does not ship: uninative-tarball.bb packages glibc, patchelf,
# libxcrypt, libnss-nis and libgcc, nothing more. The uninative loader searches
# RUNPATH and its own sysroot and never the host default paths, so rustc cannot
# start and bootstrap fails on `rustc -vV` returning 127:
#
#   rust-snapshot/bin/rustc: error while loading shared libraries: libz.so.1
#
# zlib-native is already staged in recipe-sysroot-native, so nothing needs
# building - the loader simply has no path to it. Append STAGING_LIBDIR_NATIVE
# after the existing $ORIGIN entries so a library the snapshot ships still wins
# over a staged one of the same name. This is the rpath the recipe already hands
# RUST_ALTERNATE_EXE_PATH; the snapshot was the one consumer left without it.
#
# Guarded on UNINATIVE_LOADER like the task it extends: without uninative the
# host loader resolves the library and there is nothing to fix.
do_rust_setup_snapshot:append () {
    if [ ! -z "${UNINATIVE_LOADER}" -a -e "${UNINATIVE_LOADER}" ]; then
        for bin in cargo rustc rustdoc; do
            patchelf ${WORKDIR}/rust-snapshot/bin/$bin \
                --set-rpath \$ORIGIN/../lib:${STAGING_LIBDIR_NATIVE}
        done
        for lib in ${WORKDIR}/rust-snapshot/lib/*.so*; do
            # lib/libLLVM-*.so is a 42-byte ld script rather than an ELF, and
            # patchelf exits non-zero on it. Use patchelf as its own ELF probe so
            # such stubs are skipped without masking a real failure below.
            patchelf "$lib" --print-rpath >/dev/null 2>&1 || continue
            patchelf "$lib" --set-rpath \$ORIGIN:${STAGING_LIBDIR_NATIVE}
        done
    fi
}
