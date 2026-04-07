FILESEXTRAPATHS:prepend := "${THISDIR}:"

SRC_URI += "file://0001-rust-fix-mismatched-lifetime-syntaxes-in-qr_code.patch \
        file://0002-fix-use-C-style-octal-literal-instead-of-C-23-0o-pre.patch \
        file://0003-fix-work-around-clang-20-crash-on-defaulted-non-memb.patch \
        file://0004-fix-include-gfx-Transform-for-unique_ptr-destructor.patch"

# Fix sysroot conflict between clang-native (meta-clang v20) and clang17-native
# (meta-clang-revival). Both layers define clang_base_deps() with the same function
# name, and the v17 version wins at parse time, injecting clang17-cross and
# compiler-rt17 into BASE_DEFAULT_DEPS. Meanwhile the :runtime-llvm append pulls in
# compiler-rt-native/libcxx-native which depend on clang-native (v20), causing both
# clang versions to land in the sysroot with conflicting LLVM static libraries.
DEPENDS:remove = "clang17-cross-${TARGET_ARCH} compiler-rt17"
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