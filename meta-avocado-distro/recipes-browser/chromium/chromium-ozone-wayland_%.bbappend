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

# Fix sysroot conflict between clang-native (meta-clang v20) and clang15/clang17-native
# (meta-clang-revival). All three layers define clang_base_deps() with the same Python
# function name; whichever class is parsed last wins and injects its versioned cross
# compiler (clang15-cross or clang17-cross) into BASE_DEFAULT_DEPS via the
# toolchain-clang append in meta-clang's clang.bbclass. Meanwhile the :runtime-llvm
# append pulls in compiler-rt-native/libcxx-native which depend on clang-native (v20),
# causing both clang versions to land in the sysroot with conflicting LLVM static
# libraries. Strip all revival-versioned deps and explicitly pin to the v20 cross compiler.
DEPENDS:remove = "clang15-cross-${TARGET_ARCH} compiler-rt15 clang17-cross-${TARGET_ARCH} compiler-rt17"
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