# One AWS C runtime per feed: see aws-crt-cpp_%.bbappend. Without build-deps
# the SDK links the shared aws-crt-cpp, and its own unversioned libraries are
# no longer swept in by the /usr/lib/* the bundled build packages.
PACKAGECONFIG:remove = "build-deps"
DEPENDS += "aws-crt-cpp"
FILES:${PN} += "${libdir}/lib*-cpp.so"
