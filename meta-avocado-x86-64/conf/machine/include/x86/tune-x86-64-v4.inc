# Settings for the GCC(1) cpu-type "x86-64-v4":
#
#     CPUs with AVX512F, AVX512BW, AVX512CD, AVX512DQ, AVX512VL.
#     See https://www.phoronix.com/news/GCC-11-x86-64-Feature-Levels for details.
#
# This tune is recommended for Intel Panther Lake, Clearwater Forest,
# and AMD Zen 4 (Ryzen 7000 / EPYC Genoa) and newer.
#
DEFAULTTUNE ?= "x86-64-v4"

# Include the previous tune to pull in PACKAGE_EXTRA_ARCHS
require conf/machine/include/x86/tune-corei7.inc

# Extra tune features
TUNEVALID[x86-64-v4] = "Enable x86-64-v4 specific processor optimizations"
TUNE_CCARGS .= "${@bb.utils.contains('TUNE_FEATURES', 'x86-64-v4', ' -march=x86-64-v4', '', d)}"

# Extra tune selections
AVAILTUNES += "x86-64-v4"
TUNE_FEATURES:tune-x86-64-v4 = "${TUNE_FEATURES:tune-x86-64} x86-64-v4"
BASE_LIB:tune-x86-64-v4 = "lib64"
TUNE_PKGARCH:tune-x86-64-v4 = "x86-64-v4"
PACKAGE_EXTRA_ARCHS:tune-x86-64-v4 = "${PACKAGE_EXTRA_ARCHS:tune-corei7-64} x86-64-v4"
QEMU_EXTRAOPTIONS_x86-64-v4 = " -cpu Skylake-Server-v4,check=false"

AVAILTUNES += "x86-64-v4-x32"
TUNE_FEATURES:tune-x86-64-v4-x32 = "${TUNE_FEATURES:tune-x86-64-x32} x86-64-v4"
BASE_LIB:tune-x86-64-v4-x32 = "libx32"
TUNE_PKGARCH:tune-x86-64-v4-x32 = "x86-64-v4-x32"
PACKAGE_EXTRA_ARCHS:tune-x86-64-v4-x32 = "${PACKAGE_EXTRA_ARCHS:tune-corei7-64-x32} x86-64-v4-x32"
QEMU_EXTRAOPTIONS_x86-64-v4-x32 = " -cpu Skylake-Server-v4,check=false"
