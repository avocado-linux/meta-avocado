FILESEXTRAPATHS:prepend := "${THISDIR}:"

SRC_URI += "file://0001-rust-fix-mismatched-lifetime-syntaxes-in-qr_code.patch"
SRC_URI += "file://0002-rust-add-v2-allocator-symbols-for-rust-1.89.patch"

# Fix sysroot conflict between clang-native (meta-clang v20) and clang17-native
# (meta-clang-revival). Both layers define clang_base_deps() with the same function
# name, and the v17 version wins at parse time, injecting clang17-cross and
# compiler-rt17 into BASE_DEFAULT_DEPS. Meanwhile the :runtime-llvm append pulls in
# compiler-rt-native/libcxx-native which depend on clang-native (v20), causing both
# clang versions to land in the sysroot with conflicting LLVM static libraries.
DEPENDS:remove = "clang17-cross-${TARGET_ARCH} compiler-rt17"
DEPENDS:append = " clang-cross-${TARGET_ARCH}"
