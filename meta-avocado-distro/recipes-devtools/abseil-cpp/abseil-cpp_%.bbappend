# Pin abseil to C++17.
#
# abseil's CMake auto-selects the highest C++ standard the compiler advertises
# when CMAKE_CXX_STANDARD is unset. With the host buildtools toolchain that
# resolves to C++20, so abseil's install step rewrites absl/base/options.h to
# ABSL_OPTION_USE_STD_ORDERING=1 (C++20 std:: ordering ABI). Its consumers
# (protobuf-native, grpc, ...) compile at the gcc default C++17, where
# std::weak_ordering does not exist, so do_compile fails with
# "'weak_ordering' has not been declared in 'std'".
#
# Pinning C++17 makes abseil's ABSL_INTERNAL_AT_LEAST_CXX20 test fail, so
# options.h keeps the C++17-safe polyfill and abseil's own objects match the
# C++17 ABI its consumers use. Applies to all classes so the target abseil
# stays consistent with the native one.
EXTRA_OECMAKE:append = " -DCMAKE_CXX_STANDARD=17"
