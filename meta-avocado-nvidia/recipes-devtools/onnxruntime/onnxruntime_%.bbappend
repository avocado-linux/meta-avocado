# We intentionally keep the meta-tegra-community onnxruntime 1.24.2 (the newer,
# CUDA-enabled build), NOT the older 1.21.0 from the r39.2.0 branch. The only
# snag on the wrynose toolchain is that 1.24.2 adds -Wno-error=sfinae-incomplete
# to OECMAKE_CXX_FLAGS: -Wsfinae-incomplete is a GCC 16 diagnostic and our
# toolchain is GCC 15.2.0. GCC hard-errors on -Wno-error=<unknown> (unlike plain
# -Wno-<unknown>, which it ignores), so the compiler probe fails. GCC 15 never
# emits this warning, so dropping just the suppression flag is safe and keeps the
# CUDA-enabled version. Revisit when the wrynose toolchain moves to GCC 16.
OECMAKE_CXX_FLAGS:remove = "-Wno-error=sfinae-incomplete"
