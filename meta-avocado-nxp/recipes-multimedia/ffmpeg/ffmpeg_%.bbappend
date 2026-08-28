# meta-python-ai enables libplacebo + shaderc in ffmpeg whenever "vulkan" is a
# distro feature. meta-freescale pins glslang/spirv-tools/spirv-headers to
# 1.3.275.0.imx on imxvulkan machines for the Vivante Vulkan driver, and
# oe-core's shaderc (2026.x) needs the 1.4 series (Vulkan 1.4 enums), so it
# cannot compile there. Nothing else in the feed pulls shaderc or libplacebo.
PACKAGECONFIG:remove:imxvulkan = "libplacebo shaderc"
