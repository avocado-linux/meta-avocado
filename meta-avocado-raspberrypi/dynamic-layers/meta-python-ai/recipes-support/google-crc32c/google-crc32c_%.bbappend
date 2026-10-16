# The library is built static, and python3-google-crc32c links that archive
# into its extension with the C compiler. libcrc32c.a is C++ and needs
# __cxa_guard_acquire from libstdc++, which the extension does not link, so it
# fails to load:
#
#   undefined symbol: __cxa_guard_acquire
#
# and `import google_crc32c` falls back to the slow pure-Python implementation
# with a warning. A shared libcrc32c carries its own libstdc++ dependency, which
# the extension then picks up through the library.
EXTRA_OECMAKE:append = " -DBUILD_SHARED_LIBS=ON"
