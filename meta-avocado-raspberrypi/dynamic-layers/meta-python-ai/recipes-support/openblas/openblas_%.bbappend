# The build's `tests` step compiles Fortran programs with the cross gfortran,
# which the Makefile invokes without --sysroot. gfortran then cannot find
# libgfortran.spec, which is in the recipe sysroot, and the build stops with
#
#   gfortran: fatal error: cannot read spec file 'libgfortran.spec'
#
# CC already carries ${TOOLCHAIN_OPTIONS}; give FC the same.
EXTRA_OEMAKE:append:class-target = ' FC="${HOST_PREFIX}gfortran ${TOOLCHAIN_OPTIONS}"'

# python3-scipy links the BLAS and LAPACK that libopenblas provides. The recipe
# builds with openmp only, which leaves out LAPACK and CBLAS, so scipy.linalg
# fails to import with
#
#   ImportError: ..._fblas...so: undefined symbol: cspmv_
#
# because the symbols are not in libblas.so.3.
#
# openmp is dropped: building LAPACK's Fortran with OpenMP needs omp_lib.mod,
# which the toolchain sysroot does not carry, and the build stops with
#
#   Fatal Error: Cannot open module file 'omp_lib.mod' for reading
#
# OpenBLAS then threads with pthreads.
PACKAGECONFIG = "lapack lapacke cblas"

# The recipe maps every aarch64 target to the generic ARMV8 kernels. OpenBLAS
# has a Cortex-A76 target, which the Pi 5 CPU is. It is set per machine: the
# Cortex-A76 kernels use instructions that older cores such as the Pi 4's do not have.
BLAS_AARCH64_ARCH:avocado-raspberrypi5 = "CORTEXA76"
