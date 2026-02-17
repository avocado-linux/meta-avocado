SUMMARY = "NVIDIA Linux Open GPU Kernel Modules"
DESCRIPTION = "Open-source kernel modules for NVIDIA GPUs (Turing and later). \
Built from NVIDIA's open-gpu-kernel-modules repository. Supports RTX 20/30/40/50 \
series GPUs for compute and display workloads."
HOMEPAGE = "https://github.com/NVIDIA/open-gpu-kernel-modules"
LICENSE = "MIT & GPL-2.0-only"
LIC_FILES_CHKSUM = "file://COPYING;md5=1d5fa2a493e937d5a4b96e5e03b90f7c"

SRC_URI = " \
    git://github.com/NVIDIA/open-gpu-kernel-modules.git;branch=main;protocol=https \
    file://nvidia-gpu-modules-load.conf \
"
SRCREV = "de3d54abf3dacfb9293d96ed1aa31b449e0d6518"

S = "${WORKDIR}/git"

inherit module

# The open kernel modules are built from the kernel-open/ subdirectory.
# The top-level Makefile dispatches into kernel-open/ when modules= target is used.
MODULES_MODULE_SYMVERS_LOCATION = "kernel-open"

# Build only the open kernel modules (not the proprietary ones)
EXTRA_OEMAKE += " \
    TARGET_ARCH='x86_64' \
    SYSSRC='${STAGING_KERNEL_DIR}' \
    SYSOUT='${STAGING_KERNEL_BUILDDIR}' \
    CC='${CC}' \
    LD='${LD}' \
    AR='${AR}' \
    NV_VERBOSE=1 \
"

# Build the open modules via the top-level Makefile target
do_compile() {
    oe_runmake KERNEL_UNAME=${KERNEL_VERSION} modules
}

do_install() {
    # Install kernel modules
    oe_runmake KERNEL_UNAME=${KERNEL_VERSION} \
        INSTALL_MOD_PATH=${D} \
        INSTALL_MOD_DIR=kernel/drivers/video/nvidia \
        modules_install

    # Install modules-load.d config for automatic loading at boot
    install -d ${D}${sysconfdir}/modules-load.d
    install -m 0644 ${WORKDIR}/nvidia-gpu-modules-load.conf \
        ${D}${sysconfdir}/modules-load.d/nvidia-gpu-modules.conf
}

# kernel-module-split (inherited via module) automatically creates:
#   kernel-module-nvidia
#   kernel-module-nvidia-modeset
#   kernel-module-nvidia-drm
#   kernel-module-nvidia-uvm
#   kernel-module-nvidia-peermem
#
# Users can install individual modules or all of them via ${PN}.

# The modules-load.d config file goes into the base package
FILES:${PN} += "${sysconfdir}/modules-load.d/nvidia-gpu-modules.conf"

# Module loading dependencies (nvidia must be loaded before modeset, etc.)
# These are normally handled by depmod, but explicit RDEPENDS ensures correct
# package resolution when installing individual modules.
RDEPENDS:kernel-module-nvidia-modeset = "kernel-module-nvidia"
RDEPENDS:kernel-module-nvidia-drm = "kernel-module-nvidia kernel-module-nvidia-modeset"
RDEPENDS:kernel-module-nvidia-uvm = "kernel-module-nvidia"
RDEPENDS:kernel-module-nvidia-peermem = "kernel-module-nvidia"

# x86-64 only -- the open kernel modules require x86_64
COMPATIBLE_HOST = "x86_64.*-linux"

# Parallel build
PARALLEL_MAKE = ""
