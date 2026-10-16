# numpy's meson build looks for a BLAS and, on a build host that has one
# installed, finds it through plain library detection. The native numpy then
# links the host's libblas and libcblas. Native binaries run under uninative
# with its own loader and library path, which cannot see the host's libraries,
# so `import numpy` fails with
#
#   ImportError: libcblas.so.3: cannot open shared object file
#
# in every recipe that imports the native numpy at build time (ONNX Runtime's
# CMake and Numba's setup.py, for example). The result also differs between
# build hosts, which defeats sstate sharing. Nothing uses BLAS from the native
# numpy, so build it without.
EXTRA_OEMESON:append:class-native = " -Dblas=none -Dlapack=none -Dallow-noblas=true"

# mesonpy_get_args() reads EXTRA_OEMESON through a variable name held in a list,
# which BitBake's static scan of the function cannot see, so a change to the
# option would not change the task hash and the old sstate artifact would be
# reused.
do_compile[vardeps] += "EXTRA_OEMESON"
