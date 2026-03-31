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

# Fix distutils.version removed in Python 3.12 (Ubuntu 22.04+)
# Replace with packaging.version which is available in the build env
do_check_llvm_version:prepend() {
    import sys
    import types
    # Inject a shim distutils.version module so existing code doesn't break
    if 'distutils' not in sys.modules:
        import packaging.version
        distutils_mock = types.ModuleType('distutils')
        version_mock = types.ModuleType('distutils.version')
        class LooseVersion:
            def __init__(self, v): self.version = packaging.version.Version(v)
            def __lt__(self, o): return self.version < o.version
            def __le__(self, o): return self.version <= o.version
            def __gt__(self, o): return self.version > o.version
            def __ge__(self, o): return self.version >= o.version
            def __eq__(self, o): return self.version == o.version
        version_mock.LooseVersion = LooseVersion
        distutils_mock.version = version_mock
        sys.modules['distutils'] = distutils_mock
        sys.modules['distutils.version'] = version_mock
}
