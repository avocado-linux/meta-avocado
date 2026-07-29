# Let the prebuilt rust snapshot find the libraries OE staged for it.
#
# With uninative enabled, rust-native's do_install dies before it starts:
#
#   rust-snapshot/bin/rustc: error while loading shared libraries: libz.so.1:
#   cannot open shared object file: No such file or directory
#
# The snapshot is a prebuilt upstream toolchain, linked against a generic host
# and expecting the host loader to find libz in /usr/lib. Under uninative the
# loader searches only the uninative tree plus each object's RUNPATH, and the
# uninative tarball ships no libz - correctly so, since OE builds zlib-native
# itself and a host copy in the tarball would shadow it. libz.so.1 IS staged, at
# recipe-sysroot-native/usr/lib; nothing points the snapshot at it.
#
# The recipe already patchelfs the snapshot for uninative but only sets the
# INTERPRETER (do_rust_setup_snapshot, meta-lts-mixins/recipes-devtools/rust/
# rust_1.92.0.bb), which is why the loader is right and the search path is not.
#
# Patch the SHARED OBJECTS, not the executables. The DT_NEEDED on libz belongs
# to lib/libLLVM.so.<ver>-rust-<ver>-stable, not to bin/rustc, and DT_RUNPATH -
# unlike the obsolete DT_RPATH - is used only for the direct dependencies of the
# object carrying it and is NOT inherited by transitive ones. Setting rustc's
# RUNPATH therefore has no effect on libLLVM's own lookup; the library has to
# carry the path itself.
#
# $ORIGIN/../lib is what the snapshot already carries and is kept so the objects
# keep finding their siblings; $ORIGIN is added because these libraries live in
# that same directory. Single quotes keep $ORIGIN literal for the dynamic
# loader instead of letting the shell expand it to nothing.
# Not every *.so* in that directory is an object. The snapshot ships
# libLLVM-<ver>.so as a 42-byte GNU ld linker script whose entire content is
#   INPUT(libLLVM.so.<ver>-rust-<ver>-stable)
# so a plain [ -f ] test passes it through and patchelf aborts the task with
# "patchelf: missing ELF header". --print-rpath is used as the ELF probe rather
# than file(1) or readelf: patchelf is already a declared dependency of this
# task, so it needs nothing new in the sysroot, and a file it cannot read is
# exactly a file it cannot patch.
do_rust_setup_snapshot:append() {
    if [ -n "${UNINATIVE_LOADER}" ] && [ -e "${UNINATIVE_LOADER}" ]; then
        for so in ${WORKDIR}/rust-snapshot/lib/*.so*; do
            [ -f "$so" ] || continue
            patchelf --print-rpath "$so" >/dev/null 2>&1 || continue
            patchelf "$so" --set-rpath '$ORIGIN:$ORIGIN/../lib:'"${STAGING_LIBDIR_NATIVE}"
        done
    fi
}
