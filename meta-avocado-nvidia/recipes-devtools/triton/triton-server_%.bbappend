# python/tritonfrontend links pybind11::module, whose include directory comes
# from CMake's FindPython. FindPython asks the interpreter it found, which is the
# native one in recipe-sysroot-native, for its include path and gets the
# interpreter's own view of it, /usr/include/python3.14. That path is then used
# as an absolute -isystem, so the compiler reads the build host's headers and
# the cross toolchain's poison-system-directories check stops the build:
#
#   cc1plus: error: include location "/usr/include/python3.14" is unsafe for
#   cross-compilation [-Werror=poison-system-directories]
#
# Presetting Python_INCLUDE_DIR makes FindPython skip that lookup, and the
# target headers in the recipe sysroot are used instead. The real target is an
# ExternalProject whose CMAKE_CACHE_ARGS list does not forward the variable, so
# the patch below passes it on.
FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"
SRC_URI:append = " file://0002-Forward-Python_INCLUDE_DIR-to-the-nested-project.patch"
EXTRA_OECMAKE:append = " -DPython_INCLUDE_DIR=${STAGING_INCDIR}/${PYTHON_DIR}"
