# The recipe sets CUDA_PYTHON_PARALLEL_LEVEL to oe.utils.cpu_count(), which
# counts the host's CPUs, not the build's share of them, and ignores
# PARALLEL_MAKE. Each cython translation unit of the CUDA bindings takes
# several GB, so on a 64-CPU host do_compile alone outgrows a 64 GiB build.
# Follow PARALLEL_MAKE, capped at 8.
# ponytail: fixed cap of 8; derive it from available memory if 8 proves too
# low or too high.
CUDA_PYTHON_PARALLEL_LEVEL = "${@min(8, oe.utils.parallel_make(d) or 1)}"
