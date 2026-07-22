SUMMARY = "NVIDIA Linux Open GPU Kernel Modules"
DESCRIPTION = "Open-source kernel modules for NVIDIA GPUs (Turing and later). \
Built from NVIDIA's open-gpu-kernel-modules repository. Supports RTX 20/30/40/50 \
series GPUs for compute and display workloads."
HOMEPAGE = "https://github.com/NVIDIA/open-gpu-kernel-modules"
LICENSE = "MIT & GPL-2.0-only"
LIC_FILES_CHKSUM = "file://COPYING;md5=1d5fa2a493e937d5a4b96e5e03b90f7c"

# nobranch=1: SRCREV below is the 595.84 release tag's commit, which is not
# reachable from the main branch tip, so a branch= check fails ("Unable to find
# revision ... in branch main"). Pin the exact commit instead.
SRC_URI = " \
    git://github.com/NVIDIA/open-gpu-kernel-modules.git;nobranch=1;protocol=https \
    file://nvidia-gpu-modules-load.conf \
"
SRCREV = "722ae84526a09ed672fbe75448e2909834ba4cce"

S = "${WORKDIR}/git"

inherit module

# The open kernel modules are built from the kernel-open/ subdirectory.
# The top-level Makefile dispatches into kernel-open/ when modules= target is used.
MODULES_MODULE_SYMVERS_LOCATION = "kernel-open"

# Build only the open kernel modules (not the proprietary ones).
# LDFLAGS='' : NVIDIA prelinks nv-kernel.o with a raw `ld` ($(LD) $(LDFLAGS) -r),
# but OE's LDFLAGS holds compiler-driver flags (-Wl,-O1 ...) that a bare `ld`
# rejects ("unrecognized option '-Wl,-O1'"). The .ko files are linked by kbuild
# with the kernel's own flags, so clearing LDFLAGS here is correct.
# ARCH='x86_64': OE exports the kernel ARCH ('x86' -- Linux puts 32/64-bit x86
# under arch/x86), but NVIDIA's kernel-open/Makefile only accepts its own arch
# names (x86_64/aarch64/...) and errors "Unsupported architecture x86". The
# kernel Makefile maps ARCH=x86_64 -> SRCARCH=x86, so this satisfies both.
EXTRA_OEMAKE += " \
    ARCH='x86_64' \
    TARGET_ARCH='x86_64' \
    SYSSRC='${STAGING_KERNEL_DIR}' \
    SYSOUT='${STAGING_KERNEL_BUILDDIR}' \
    CC='${CC}' \
    LD='${LD}' \
    AR='${AR}' \
    LDFLAGS='' \
    NV_VERBOSE=1 \
"

# Build the open modules via the top-level Makefile target
do_compile() {
    oe_runmake KERNEL_UNAME=${KERNEL_VERSION} modules
}

do_install() {
    # Install kernel modules. Use MODLIB (as module.bbclass does) rather than
    # INSTALL_MOD_PATH=${D}: the kernel's modules_install hardcodes .../lib/...,
    # which lands at a literal ${D}/lib/modules, but on usrmerge systems the
    # kernel-module-split scans ${nonarch_base_libdir}/modules (= ${D}/usr/lib/
    # modules), so modules installed to /lib were "installed but not shipped".
    # MODLIB points the install straight at the directory the split scans.
    # DEPMOD=echo avoids running (cross) depmod during install.
    oe_runmake KERNEL_UNAME=${KERNEL_VERSION} \
        MODLIB=${D}${nonarch_base_libdir}/modules/${KERNEL_VERSION} \
        INSTALL_MOD_DIR=kernel/drivers/video/nvidia \
        DEPMOD=echo \
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
