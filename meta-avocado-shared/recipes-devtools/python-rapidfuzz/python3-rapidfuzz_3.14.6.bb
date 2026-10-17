SUMMARY = "Rapid fuzzy string matching"
DESCRIPTION = "RapidFuzz computes string similarity and distances (Levenshtein, Jaro-Winkler and others) with a C++ implementation."
HOMEPAGE = "https://github.com/rapidfuzz/RapidFuzz"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://LICENSE;md5=dcd1023081943827dd63f01dc3fda218"

# The sdist carries the Cython-generated .cxx files and vendors rapidfuzz-cpp
# and taskflow, so no Cython and no network are needed.
SRC_URI[sha256sum] = "e13a8160d017b499ec7a2fa9d0ce1ae2e7377080815785819f966fb235d4eb60"

PYPI_PACKAGE = "rapidfuzz"

inherit pypi pkgconfig python_setuptools_build_meta

DEPENDS = " \
    python3-scikit-build-core-native \
    cmake-native \
    ninja-native \
"

# Without this the build installs the pure-Python fallback when the C++
# extension fails to compile, and says so only in a message.
export RAPIDFUZZ_BUILD_EXTENSION = "1"

PEP517_BUILD_OPTS = " \
    --skip-dependency-check \
    -Ccmake.define.CMAKE_FIND_ROOT_PATH_MODE_PACKAGE=ONLY \
    -Ccmake.define.CMAKE_FIND_ROOT_PATH_MODE_PROGRAM=ONLY \
    -Ccmake.define.CMAKE_FIND_ROOT_PATH_MODE_LIBRARY=ONLY \
    -Ccmake.define.CMAKE_FIND_ROOT_PATH_MODE_INCLUDE=ONLY \
    -Ccmake.define.CMAKE_FIND_ROOT_PATH='${STAGING_DIR_NATIVE}' \
    -Ccmake.build-type='RelWithDebInfo' \
    -Cbuild-dir='${B}' \
"

RDEPENDS:${PN} += "python3-core"

# The CMake install step copies its own cmake_install.cmake into the package
# next to each extension, with TMPDIR paths in it, and the [buildpaths] QA check
# rejects them. They are build files and not part of the module.
do_install:append() {
    rm -f ${D}${PYTHON_SITEPACKAGES_DIR}/rapidfuzz/cmake_install.cmake
    rm -f ${D}${PYTHON_SITEPACKAGES_DIR}/rapidfuzz/distance/cmake_install.cmake
}
