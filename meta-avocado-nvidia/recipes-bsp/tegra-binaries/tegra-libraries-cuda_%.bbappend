# SPDX-License-Identifier: MIT
#
# History: on L4T R36.5 (JP6.2) we added
#   RDEPENDS:${PN}:tegra234 += "tegra-libraries-dla-compiler"
# because tegra-libraries-cuda ships libnvcudla.so, which dlopen()s
# libnvdla_compiler.so at runtime (cuDLA / the TensorRT execution provider).
# That .so isn't in DT_NEEDED, so shlibdeps never pulls the compiler package
# in automatically, and GPU containers using cuDLA failed at provider init
# with "libnvdla_compiler.so: cannot open shared object file" (the
# nvidia-container-toolkit drivers.csv references it, but the host file was
# absent so the mount was a silent no-op).
#
# L4T R39.2.0 (JP7.x): there is NO tegra-libraries-dla-compiler package in
# meta-tegra/meta-tegra-community for ANY machine — the recipe was dropped and
# libnvdla_compiler.so now survives only as a drivers.csv passthrough entry.
# An RDEPENDS on it is unsatisfiable and makes every tegra234 rootfs
# unbuildable ("Nothing RPROVIDES 'tegra-libraries-dla-compiler'"), so the dep
# is intentionally NOT declared here.
#
# If DLA compilation is needed on JP7 and a future meta-tegra bump reintroduces
# the package (or ships libnvdla_compiler.so elsewhere), re-add the dependency
# here, scoped to the machines that actually have the DLA compiler blob.
