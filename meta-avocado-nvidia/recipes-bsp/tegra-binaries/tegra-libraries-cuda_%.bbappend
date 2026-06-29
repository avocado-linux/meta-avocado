# SPDX-License-Identifier: MIT
#
# tegra-libraries-cuda ships libnvcudla.so but its DT_NEEDED does not list
# libnvdla_compiler.so — cuDLA loads the compiler via dlopen at runtime, and
# the same applies to the TensorRT execution provider. Yocto's automatic
# shlibdeps scanner therefore misses the dependency and tegra-libraries-dla-compiler
# never lands in the rootfs.
#
# Symptom: GPU containers using cuDLA / TRT EP fail at provider init with
#   libnvdla_compiler.so: cannot open shared object file
# even though the nvidia-container-toolkit CSV at
#   /etc/nvidia-container-runtime/host-files-for-container.d/drivers.csv
# references /usr/lib/libnvdla_compiler.so. With the file absent the mount
# is silently a no-op.
#
# The runtime sibling (libnvdla_runtime.so) IS in DT_NEEDED and gets picked
# up by shlibdeps, which is why tegra-libraries-cuda's generated requires
# include libnvdla_runtime.so()(64bit) but not the compiler.
#
# Prior art: OE4T/meta-tegra#1281 (closed without a recipe-level fix).
#
# Verified on L4T R36.5 (JP6.2) Orin NX.
#
# Scoped to tegra234 — tegra-libraries-dla-compiler itself declares
# COMPATIBLE_MACHINE = "(tegra234)" (the DLA hardware + companion compiler
# blob only ship for Orin in the L4T BSP). On tegra264 (Thor) the package
# doesn't exist, so an unscoped append makes the rootfs unbuildable.
RDEPENDS:${PN}:tegra234 += "tegra-libraries-dla-compiler"
