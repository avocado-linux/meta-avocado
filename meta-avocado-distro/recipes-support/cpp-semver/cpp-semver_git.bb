SUMMARY = "Header-only C++ semantic versioning library"
DESCRIPTION = "cpp-semver parses, compares and constrains Semantic Versioning 2.0.0 \
version strings. It is a single header with a CMake package config."
HOMEPAGE = "https://github.com/z4kn4fein/cpp-semver"
SECTION = "libs"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://LICENSE;md5=0bb90645bbff43c8131524d02976cbc0"

# The branch tip, not the v0.4.0 tag: the code that consumes this builds against
# main, which is newer than the last tag.
PV = "0.4.0+git"
SRC_URI = "git://github.com/z4kn4fein/cpp-semver.git;protocol=https;branch=main"
SRCREV = "48ba35ebe3588906d623739e760de2b3529e97af"

inherit cmake

# Install is on by default only for a top-level project; say so rather than
# rely on that. The tests fetch a test framework over the network.
EXTRA_OECMAKE += "-DSEMVER_BUILD_TESTS=OFF -DSEMVER_INSTALL=ON"

# Header-only: everything lands in -dev, and the empty main package must still
# be created so the group that names it resolves.
ALLOW_EMPTY:${PN} = "1"
RDEPENDS:${PN}-dev = ""
