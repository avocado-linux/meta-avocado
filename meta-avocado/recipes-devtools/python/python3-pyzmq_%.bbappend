# pyzmq's CMake finds libzmq with find_package(ZeroMQ) first and, when that
# fails, with pkg-config. The recipe confines find_package to the native
# sysroot, so the target's ZeroMQConfig.cmake is never found and the pkg-config
# fallback runs. On a build host that has libzmq's development files installed,
# that lookup can return the host's libzmq.pc instead of the sysroot's, and the
# compile line then carries the host's include directories:
#
#   cc1: error: include location "/usr/include/p11-kit-1" is unsafe for
#   cross-compilation [-Werror=poison-system-directories]
#
# The failure depends on what the build host has installed, so it never shows
# on a clean CI host. Name the target's config directory so find_package
# succeeds and the pkg-config fallback is not reached.
PEP517_BUILD_OPTS:append = " -Ccmake.define.ZeroMQ_DIR=${STAGING_LIBDIR}/cmake/ZeroMQ"
