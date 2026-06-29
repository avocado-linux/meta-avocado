# CUDA 13.2 (L4T r39 / Thor BSP) ships target headers under
# targets/<arch>-linux/. The recipe sets CUDA_INSTALL_ARCH:class-target = "sbsa"
# so the do_compile flattening in cuda-shared-binaries.inc finds the deb's
# layout for target builds, but leaves :class-nativesdk to fall back to the
# default ${HOST_ARCH}. The arm64 deb ships targets/sbsa-linux/ while the
# amd64 deb ships targets/x86_64-linux/, so an aarch64 SDK needs "sbsa" but
# an x86_64 SDK needs "x86_64" — otherwise the flatten silently no-ops and
# FILES misses the targets/.../ subtree, tripping a fatal "Files/directories
# were installed but not shipped" QA check on do_package.
CUDA_INSTALL_ARCH:class-nativesdk = "${@'sbsa' if d.getVar('HOST_ARCH') == 'aarch64' else d.getVar('HOST_ARCH')}"
