# cmake's bundled cmcurl binds to the host's nghttp2 at configure time and then
# cannot compile against it, because /usr/include is not on the task's
# include path:
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
