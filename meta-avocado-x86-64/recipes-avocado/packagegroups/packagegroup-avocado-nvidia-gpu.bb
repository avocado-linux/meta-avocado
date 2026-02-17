DESCRIPTION = "Packagegroups for NVIDIA discrete GPU compute support"
SUMMARY = "NVIDIA GPU compute support (all supported series)"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup

PACKAGES = " \
    ${PN}-rtx-40 \
    ${PN}-rtx-50 \
    ${PN} \
"

# Shared: kernel modules needed for any GPU series
NVIDIA_MODULES_CORE = " \
    kernel-module-nvidia \
    kernel-module-nvidia-modeset \
    kernel-module-nvidia-drm \
"

# Compute-specific kernel modules
NVIDIA_MODULES_COMPUTE = " \
    kernel-module-nvidia-uvm \
"

# Userspace components and firmware
NVIDIA_USERSPACE = " \
    nvidia-gpu-userspace \
    nvidia-gpu-firmware \
"

# RTX 40 series (Ada Lovelace)
SUMMARY:${PN}-rtx-40 = "NVIDIA RTX 40-series GPU compute support"
RDEPENDS:${PN}-rtx-40 = " \
    ${NVIDIA_MODULES_CORE} \
    ${NVIDIA_MODULES_COMPUTE} \
    ${NVIDIA_USERSPACE} \
"

# RTX 50 series (Blackwell)
SUMMARY:${PN}-rtx-50 = "NVIDIA RTX 50-series GPU compute support"
RDEPENDS:${PN}-rtx-50 = " \
    ${NVIDIA_MODULES_CORE} \
    ${NVIDIA_MODULES_COMPUTE} \
    ${NVIDIA_USERSPACE} \
"

# Catch-all: installs everything for any supported GPU
RDEPENDS:${PN} = " \
    ${PN}-rtx-40 \
    ${PN}-rtx-50 \
"
