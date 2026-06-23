FILESEXTRAPATHS:prepend := "${THISDIR}:"

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