# Disable IDN support in cmake's bundled curl (Utilities/cmcurl).
#
# cmcurl probes for libidn2 with check_library_exists_concat (CMakeLists.txt
# around USE_LIBIDN2), a bare link test that is NOT sysroot-restricted. On a
# host whose base package ships the libidn2 dev symlink - Arch and derivatives
# do; Debian/Ubuntu split it into libidn2-dev, which is why this never fires
# there - the probe finds /usr/lib/libidn2.so and adds -lidn2 to the link line.
# The matching header check IS sysroot-restricted and fails, so the CMake cache
# ends up with HAVE_IDN2_H empty and HAVE_LIBIDN2=1. That asymmetry is the
# fingerprint of a host-library leak.
#
# Nothing provides a libidn2-native, so the resulting cmake binary carries a
# DT_NEEDED on a library absent from recipe-sysroot-native. That stayed
# invisible while native binaries ran under the host loader, which searches
# /usr/lib. Under uninative the loader searches only the uninative tree plus
# RUNPATH, so do_install dies the first time it runs its own output:
#
#   bin/cmake: error while loading shared libraries: libidn2.so.0:
#   cannot open shared object file: No such file or directory
#
# Fixing the leak rather than shipping libidn2 in the uninative tarball: the
# tarball mirrors what upstream uninative provides, and masking this would
# leave the next host-only library to fail the same way.
#
# IDN is dead weight for how cmake uses curl (fetching files during a build).
# The recipe already carries 0001-CMakeLists.txt-disable-USE_NGHTTP2.patch,
# which turns off another bundled-curl feature for the same class of reason.
# NOTE: -DUSE_LIBIDN2=0 does NOT work and was tried first. cmcurl's
# CMakeLists.txt does a plain `set(USE_LIBIDN2 ON)` at line 90, before the
# `option(USE_LIBIDN2 ...)` at 1019. A plain set() creates a NORMAL variable,
# which shadows the cache variable that -D populates, so `if(USE_LIBIDN2)` at
# line 1020 reads ON no matter what is passed on the command line and the probe
# runs anyway. Verified: -DUSE_LIBIDN2=0 was present in the bootstrap line and
# HAVE_LIBIDN2 still came out 1.
#
# Pre-seed the RESULT variable instead. check_library_exists() skips its test
# when the result variable is already in the cache, so check_library_exists_concat
# (CMake/Macros.cmake:31) leaves HAVE_LIBIDN2 false and never appends idn2 to
# CURL_LIBS. This is the same idiom the recipe already uses for ACL
# (-DENABLE_ACL=0 -DHAVE_ACL_LIBACL_H=0 -DHAVE_SYS_ACL_H=0).
CMAKE_EXTRACONF += "-DHAVE_LIBIDN2=0"
