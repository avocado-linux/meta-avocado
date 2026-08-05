# cmake's bundled cmcurl binds to host libraries at configure time and then
# cannot compile against them, because /usr/include is not on the task's
# include path. Two separate probes leak, each needing a different lever.
#
# nghttp2 - cmake vendors it, so the fix is its own bundling switch:
#
#   -- Found NGHTTP2: /usr/include (found version "1.70.0")
#   cmcurl/lib/dynhds.h:179:10: fatal error: nghttp2/nghttp2.h: No such file
#
# cmake-native_4.3.1.bb already opts out of seven system libraries, and its
# e2fsprogs opt-out states the reason: "Ensure e2fsprogs isn't found on the host
# to remove a build dependency and reproducible builds." nghttp2 has no such
# entry, so a host carrying its headers builds differently from one without -
# and only the former fails.
EXTRA_OECMAKE += "-DCMAKE_USE_SYSTEM_LIBRARY_NGHTTP2=0"

# libidn2 - not vendored, so there is no bundling switch, and neither of the
# two obvious levers works:
#
#   cmcurl/lib/idn.c:33:10: fatal error: idn2.h: No such file or directory
#
#   * -DUSE_LIBIDN2=OFF is inert. cmcurl/CMakeLists.txt:101 does an
#     unconditional set(USE_LIBIDN2 ON) as a normal variable, so the
#     option() at :1404 never touches the cache (CMP0077).
#   * -DHAVE_LIBIDN2=0 -DHAVE_IDN2_H=0 is inert for a subtler reason: :1411
#     and :1412 set both as normal variables whenever find_package succeeds,
#     overwriting whatever the cache holds.
#
# The only state that decides the outcome is LIBIDN2_FOUND, so disable the
# find itself. CMake's own CMAKE_DISABLE_FIND_PACKAGE_<pkg> forces the
# find_package(Libidn2 QUIET) at :1408 to fail, leaving HAVE_IDN2_H and
# HAVE_LIBIDN2 at their OFF defaults from :1405 and :1406.
EXTRA_OECMAKE += "-DCMAKE_DISABLE_FIND_PACKAGE_Libidn2=1"
