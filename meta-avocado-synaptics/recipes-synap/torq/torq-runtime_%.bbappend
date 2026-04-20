# IREE's ukernel micro-kernels compile individual C files with per-file
# -march=armv8.2-a+<ext> flags (i8mm, bf16, fp16, fp16fml, dotprod).
# GCC rejects the combination of -mcpu=cortex-a73+crc (which implies armv8.0-a)
# with -march=armv8.2-a+*, producing hard errors like:
#   cc1: error: switch '-mcpu=cortex-a73+crc' conflicts with '-march=armv8.2-a+i8mm'
# Replacing -mcpu with an equivalent -march + -mtune avoids this conflict while
# preserving Cortex-A73 scheduling optimizations.
TARGET_CC_ARCH:remove = "-mcpu=cortex-a73+crc"
TARGET_CC_ARCH:append = " -march=armv8-a+crc -mtune=cortex-a73"
