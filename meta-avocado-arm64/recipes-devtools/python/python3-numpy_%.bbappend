# numpy 2.4.3 bundles Highway. Under -march=armv9-a, GCC 15 makes SVE2
# Highway's static target, and numpy's np::simd wrappers then fail to inline
# Highway's SVE2 ops ("inlining failed in call to always_inline
# hwy::N_SVE2::Set ...: target specific option mismatch"), so do_compile fails.
# Compile numpy with SVE2 off: the static target falls back to SVE, and numpy's
# runtime dispatch is unchanged.
NUMPY_NOSVE2 = "${@' '.join(f + '+nosve2' for f in d.getVar('TUNE_CCARGS').split() if f.startswith('-march='))}"
CFLAGS:append:arm64-uefi-v9 = " ${NUMPY_NOSVE2}"
CXXFLAGS:append:arm64-uefi-v9 = " ${NUMPY_NOSVE2}"
