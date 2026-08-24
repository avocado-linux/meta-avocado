FILESEXTRAPATHS:prepend := "${THISDIR}:"

# Re-include our fixed gn-utils.inc so its write_toolchain_file (with the
# rust-linker cc_wrapper fix) overrides upstream's. Upstream
# meta-browser/meta-chromium's chromium-gn.inc does a bare `require
# gn-utils.inc`, which bitbake resolves to the copy in ITS OWN directory - our
# same-named file under meta-avocado-distro is never consulted by that require.
# A bbappend is parsed after the base recipe and all its requires, so requiring
# our copy here re-runs its `def write_toolchain_file` (and the sibling arch
# helpers) last, and the last python-function definition wins. The
# GN_TARGET_ARCH_NAME:<arch> lines in the file are override assignments, so the
# re-include is idempotent for them.
require ${THISDIR}/gn-utils.inc

SRC_URI += "file://0001-rust-fix-mismatched-lifetime-syntaxes-in-qr_code.patch \
        file://0002-fix-use-C-style-octal-literal-instead-of-C-23-0o-pre.patch \
        file://0003-fix-work-around-clang-20-crash-on-defaulted-non-memb.patch \
        file://0004-fix-include-gfx-Transform-for-unique_ptr-destructor.patch"

# meta-qcom-hwe's chromium-browser-layer/.../chromium-ozone-wayland_%.bbappend
# layers a `fix-chromium-launch-crash.patch` workaround written against an
# older chromium where xdg_toplevel_set_min_size / SetMaximized had different
# signatures. Chromium 146 refactored those, so the patch fails to apply.
SRC_URI:remove:qcom = "file://fix-chromium-launch-crash.patch"

# Deterministically pin chromium to the meta-clang v20 cross-toolchain and strip ALL of
# meta-clang-revival's versioned clang deps (14/15/16/17).
#
# Root cause of the "basehash value changed on reparse / metadata is not deterministic"
# error AND the "clang installed by both clang-cross-aarch64 and clang16-cross-aarch64"
# sysroot collision: meta-clang (v20) and meta-clang-revival (14-17) are BOTH active when a
# target pulls clang.yml (chromium needs v20) and python-ai.yml (DRP-AI brings revival).
# meta-clang v20 does an override ASSIGNMENT `BASE_DEFAULT_DEPS:toolchain-clang:class-target =
# ${@clang_base_deps(d)}` (v20 deps), while revival's toolchain/clang.inc does an UNCONDITIONAL
# `BASE_DEFAULT_DEPS:append = " compiler-rt${CLANGMAJORVERSION} libcxx${CLANGMAJORVERSION}"`.
# Whether revival's append lands ON TOP of v20's assignment or is RESET by it depends on class
# parse order — which is NOT stable across a reparse (parser-cache eviction under memory
# pressure at full fan-out). So BASE_DEFAULT_DEPS flips between "v20" and "v20 + v16" between
# parse and reparse: that flips the task basehash (the determinism error), and when both land
# both clang-cross versions hit the sysroot (the collision).
#
# Fix: strip revival's versioned deps from BOTH BASE_DEFAULT_DEPS (the racy variable) and
# DEPENDS. `:remove` is applied at FINALIZATION — after the assignment and the append, whatever
# the parse order — so the result is deterministically v20-only regardless of which class parsed
# last. That removes the basehash non-determinism by construction and ends the sysroot collision.
# Scoped to chromium (which wants v20); recipes that genuinely need revival's clang are untouched.
CLANG_REVIVAL_DEPS = "\
    compiler-rt14 libcxx14 clang14-cross-${TARGET_ARCH} \
    compiler-rt15 libcxx15 clang15-cross-${TARGET_ARCH} \
    compiler-rt16 libcxx16 clang16-cross-${TARGET_ARCH} \
    compiler-rt17 libcxx17 clang17-cross-${TARGET_ARCH} "
BASE_DEFAULT_DEPS:remove = "${CLANG_REVIVAL_DEPS}"
DEPENDS:remove = "${CLANG_REVIVAL_DEPS}"
DEPENDS:append = " clang-cross-${TARGET_ARCH}"

# V8's mksnapshot is cross-compiled for aarch64 and run under QEMU user-mode
# during the build. Two features cause mksnapshot to SIGTRAP (signal 5) under
# QEMU:
# 1. arm_control_flow_integrity="standard" enables BTI/PAC instructions
#    (ARMv8.5/8.3) via -mbranch-protection=standard. Cortex-A72 lacks these
#    extensions and QEMU's enforcement of BTI landing pads in V8's JIT code
#    causes traps.
# 2. v8_enable_sandbox reserves a large virtual memory cage that QEMU user-mode
#    cannot satisfy, hitting a CHECK failure.
GN_ARGS += 'arm_control_flow_integrity="none"'
GN_ARGS += "v8_enable_sandbox=false"
GN_ARGS += "v8_enable_webassembly=false"

# meta-qcom-hwe's dynamic-layers/chromium-browser-layer/.../
# chromium-ozone-wayland_%.bbappend has `GN_ARGS:append = "symbol_level=1"`
# without a leading space, which raw-concatenates with whatever GN_ARGS ends
# with at expansion time (e.g. "v8_enable_webassembly=falsesymbol_level=1"),
# which gn rejects with "Operator requires a rvalue."
# Inject a trailing space at parse time so the broken :append lands on
# whitespace.
GN_ARGS += " "

# ninja's Rust allocator-error-handler link step (obj/build/rust/allocator/
# liballoc_error_handler_impl.a) invokes the plain clang-native binary directly
# as a universal cross-compiler (--target=aarch64-unknown-linux-gnu, LLVM's
# canonical triple), so compiler-rt's builtins have to exist under THAT triple
# in recipe-sysroot-native. Staging them there is upstream's own
# do_copy_clang_library -- but it derives the canonical triple with
#
#     sed 's:-oe-:-unknown-:'
#
# which hardcodes OE-core's default TARGET_VENDOR. avocado.inc sets
# TARGET_VENDOR = "-avocado", so RUST_TARGET_SYS is aarch64-avocado-linux-gnu,
# the substitution is a no-op, and the archive lands in
# latest/lib/aarch64-avocado-linux-gnu/ while ninja looks in
# latest/lib/aarch64-unknown-linux-gnu/ -- "missing and no known rule to make
# it". Upstream meta-browser 7172778 fixes this with 's:${TARGET_VENDOR}-:',
# and scarthgap carried the same fix in a full chromium-gn.inc override that
# the wrynose port dropped; this is that fix, re-applied as a function
# override so no whole .inc has to be forked.
#
# Redefining the function here rather than patching it: a bbappend is parsed
# after the base recipe and all its requires, so the last definition wins --
# the same mechanism the gn-utils.inc require above relies on.
#
# Deltas from upstream's body, both carried over from the scarthgap version:
#   - the vendor is matched as -[^-]*- so this holds for any TARGET_VENDOR
#     (-oe, -avocado, -poky) instead of trading one hardcoded vendor for
#     another
#   - versioned clang dirs are searched newest-first (sort -rV) and copied
#     with cp -n, so a stale lower-version compiler-rt tree left in the
#     sysroot cannot shadow the current one
do_copy_clang_library () {
    cp -r "${STAGING_LIBDIR_NATIVE}/clang/latest" "${STAGING_DIR_HOST}${nonarch_libdir}/clang/"
    cd "${STAGING_DIR_HOST}${nonarch_libdir}/clang" || return

    versioned_dirs=$(find . -maxdepth 1 -mindepth 1 \! -name latest -type d | sort -rV)
    lib_file=$(find $versioned_dirs \( -name "libclang_rt.builtins-*" -o -name "liborc_rt-*" \) | sort -u)
    echo "lib_file = $lib_file"
    export CHROMIUM_TARGET_TRIPLET="$(echo ${RUST_TARGET_SYS} | sed 's:-[^-]*-:-unknown-:')"

    mkdir -p "latest/lib/${CHROMIUM_TARGET_TRIPLET}"
    echo "Executing cp $lib_file latest/lib/${CHROMIUM_TARGET_TRIPLET}/"
    for f in $lib_file; do
        cp -n "$f" "latest/lib/${CHROMIUM_TARGET_TRIPLET}/"
    done
    cd "latest/lib/${CHROMIUM_TARGET_TRIPLET}/" || return

    for file in *-"${TARGET_ARCH}".a *-"${TARGET_ARCH}hf".a; do
        if [ -f "$file" ]; then
            new_name=$(echo "$file" | sed -e "s/-${TARGET_ARCH}hf//" -e "s/-${TARGET_ARCH}//")
            mv "$file" "$new_name"
        fi
    done

    native_arch_path="${STAGING_LIBDIR_NATIVE}/clang/latest/lib/${CHROMIUM_TARGET_TRIPLET}/"
    mkdir -p "$native_arch_path"
    echo "Executing cp -r $(ls -d *) $native_arch_path"
    cp -r * "$native_arch_path"

    if [ "${TARGET_ARCH}" != "${BUILD_ARCH}" ]; then
        export CHROMIUM_BUILD_TRIPLET="$(echo ${RUST_BUILD_SYS} | sed 's:-[^-]*-:-unknown-:')"
        cd "${STAGING_LIBDIR_NATIVE}/clang"
        rm -rf "latest/lib/${CHROMIUM_BUILD_TRIPLET}"
        cp -ar latest/lib/linux "latest/lib/${CHROMIUM_BUILD_TRIPLET}"
        cd "latest/lib/${CHROMIUM_BUILD_TRIPLET}"

        for file in *-"${BUILD_ARCH}".a *-"${BUILD_ARCH}hf".a; do
            if [ -f "$file" ]; then
                new_name=$(echo "$file" | sed -e "s/-${BUILD_ARCH}hf//" -e "s/-${BUILD_ARCH}//")
                mv "$file" "$new_name"
            fi
        done
    fi
}
