FILESEXTRAPATHS:prepend := "${THISDIR}:"

SRC_URI += "file://0001-rust-fix-mismatched-lifetime-syntaxes-in-qr_code.patch"
SRC_URI += "file://0002-fix-0o-octal-literals-for-clang-20.patch"
SRC_URI += "file://0003-workaround-clang-20-crash-in-defaulted-operator-eq.patch"
SRC_URI += "file://0004-fix-xr_rigid_transform-incomplete-type-in-unique_ptr.patch"

# Fix sysroot conflict between clang-cross (meta-clang v20) and clangNN-cross
# (meta-clang-revival). All versioned clangNN bbclasses redefine clang_base_deps()
# with the same function name as clang.bbclass. Due to BitBake's global method pool,
# the last-parsed version wins, injecting clangNN-cross and compiler-rtNN into
# BASE_DEFAULT_DEPS instead of the intended clang-cross and compiler-rt. Which
# version wins depends on non-deterministic parse order. Remove all versioned
# variants and force the correct unversioned dependencies from meta-clang.
DEPENDS:remove = "clang15-cross-${TARGET_ARCH} clang16-cross-${TARGET_ARCH} clang17-cross-${TARGET_ARCH}"
DEPENDS:remove = "compiler-rt15 compiler-rt16 compiler-rt17"
DEPENDS:append = " clang-cross-${TARGET_ARCH} compiler-rt"

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
