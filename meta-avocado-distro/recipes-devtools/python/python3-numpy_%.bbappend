# numpy's meson build looks for BLAS and LAPACK by name. In the native build
# that lookup also finds the build host's libraries, and the extension then
# links /usr/lib/libcblas.so.3 by absolute path. BitBake runs native Python
# under the buildtools loader, which cannot resolve that path, so a recipe that
# imports numpy-native (python3-cupy, for one) stops with "libcblas.so.3:
# cannot open shared object file". It also makes the native sstate signature
# depend on which BLAS the builder has installed.
#
# Native numpy only runs build-time helpers, so build it without BLAS. The
# target build is unaffected: its sysroot has no BLAS to find.
EXTRA_OEMESON:append:class-native = " -Dblas=none -Dlapack=none"

# python_mesonpy reads EXTRA_OEMESON through a loop over variable names in
# mesonpy_get_args(), which BitBake's code parser cannot follow. Without this
# line a change to EXTRA_OEMESON leaves the do_compile signature unchanged, and
# the old BLAS-linked native numpy keeps coming back from sstate.
do_compile[vardeps] += "EXTRA_OEMESON"
