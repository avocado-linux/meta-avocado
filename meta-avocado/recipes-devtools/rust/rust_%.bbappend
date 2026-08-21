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
# patchelf-uninative, not patchelf, and so no [depends] on patchelf-native. Bare
# patchelf is in neither HOSTTOOLS nor HOSTTOOLS_NONFATAL and would need one; the
# uninative binary needs none, because inside this guard it is already there.
# uninative.bbclass prepends the uninative bindir to PATH (uninative.bbclass:151)
# and uninative-tarball.bb installs its patchelf under that name
# (uninative-tarball.bb:63), so the tool exists exactly when UNINATIVE_LOADER
# does - the same condition the guard below tests. oe-core scarthgap
# rust_1.75.0 patches the snapshot this way for the same reason.
#
# The alternative was re-declaring patchelf-native:do_populate_sysroot here,
# which put a build on rust's critical path for a tool the build already had, and
# bound to a task name: rename do_rust_setup_snapshot and the varflag is set on a
# task that never runs, never warns, and never applies.

# Ensure every remaining argument appears in $1's RUNPATH, appending only what is
# missing and never dropping an entry the object already carries. Both loops below
# go through this, so neither can assert a fixed rpath over one it did not read.
#
# Two properties the loops depend on:
#
#   Skips an object patchelf cannot read. lib/libLLVM-*.so is a 42-byte ld script
#   rather than an ELF and patchelf exits non-zero on it. This reads as "not an
#   ELF" only because the task checks for the tool itself first - without that
#   check the same line would swallow a missing patchelf-uninative.
#
#   Idempotent. The task carries [dirs], not [cleandirs], so nothing guarantees a
#   clean ${WORKDIR}/rust-snapshot: `bitbake -f -c rust_setup_snapshot` over a
#   surviving one would otherwise append a second copy of STAGING_LIBDIR_NATIVE
#   per forced run, growing the dynstr and making -f non-equivalent to a clean run.
rust_snapshot_ensure_rpath() {
    obj=$1
    shift
    existing=$(patchelf-uninative "$obj" --print-rpath 2>/dev/null) || return 0
    rpath=$existing
    for entry in "$@"; do
        case ":$rpath:" in
            *":$entry:"*) ;;
            *) if [ -n "$rpath" ]; then rpath="$rpath:$entry"; else rpath=$entry; fi ;;
        esac
    done
    [ "$rpath" = "$existing" ] && return 0
    patchelf-uninative "$obj" --set-rpath "$rpath"
}

do_rust_setup_snapshot:append () {
    if [ ! -z "${UNINATIVE_LOADER}" -a -e "${UNINATIVE_LOADER}" ]; then
        # Checked once, here, so the per-object skip in rust_snapshot_ensure_rpath
        # cannot stand in for an absent tool. It is a guard against the uninative
        # layout changing, not against a missing dependency - see the note above.
        command -v patchelf-uninative >/dev/null 2>&1 || bbfatal "patchelf-uninative not found on PATH despite UNINATIVE_LOADER being set"

        for bin in cargo rustc rustdoc; do
            rust_snapshot_ensure_rpath ${WORKDIR}/rust-snapshot/bin/$bin \
                '$ORIGIN/../lib' "${STAGING_LIBDIR_NATIVE}"
        done

        # Only the staging dir is ensured here: these objects already carry
        # $ORIGIN/../lib, and ensuring it too would be a no-op rather than a fix.
        found=0
        for lib in ${WORKDIR}/rust-snapshot/lib/*.so*; do
            [ -e "$lib" ] || continue
            found=1
            rust_snapshot_ensure_rpath "$lib" "${STAGING_LIBDIR_NATIVE}"
        done
        if [ "$found" = 0 ]; then
            bbwarn "rust-snapshot/lib holds no shared libraries: the libz.so.1 edge this append closes is reached through libLLVM's RUNPATH, so a snapshot without them needs a re-audit rather than a silent skip"
        fi
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
