# Fix kernel-devsrc package to include generated headers needed for
# out-of-tree kernel module compilation.
#
# ARM64 (and some other architectures) have asm/types.h as a generated header
# in arch/${ARCH}/include/generated/, not in the kernel source tree.
# The upstream kernel-devsrc.bb copies arch/${ARCH}/include from ${S} (source)
# but misses the generated headers from ${B} (build directory).
#
# This bbappend copies the generated headers and creates necessary symlinks.

# One package per kernel. A multi-kernel feed carries a kernel-devsrc for each
# kernel it builds, and kernelsrc.bbclass versions them all by the upstream
# part of KERNEL_VERSION alone (6.8.12 for both L4T releases, 6.18.52 for the
# stock and PREEMPT_RT kernels). Under one NAME, dnf just takes the newest, so
# an out-of-tree module compiles against the wrong kernel's headers.
#
# Name each package after the full KERNEL_VERSION, like the kernel recipe's own
# packages (avocado-kernel-feed.bbclass). avocado-cli excludes every other
# kernel's `kernel-*<kver>` packages from an install, so a bare `kernel-devsrc`
# request resolves to the selected kernel. RREPLACES keeps the bare names as
# Provides, and obsoletes the old unversioned packages on upgrade.
#
# KERNEL_VERSION comes from the kernel's build dir, so it is unknown at parse
# time. Pin its signature value, as kernel.bbclass does for
# KERNEL_VERSION_PKG_NAME. do_install depends on virtual/kernel, so a new
# kernel still rebuilds and repackages this recipe.
KERNEL_DEVSRC_KVER = "${@d.getVar('KERNEL_VERSION') or 'unknown'}"
KERNEL_DEVSRC_KVER[vardepvalue] = "kernel-version"

PKG:${PN} = "${PN}-${KERNEL_DEVSRC_KVER}"
PKG:${PN}-dev = "${PN}-dev-${KERNEL_DEVSRC_KVER}"
PKG:${PN}-dbg = "${PN}-dbg-${KERNEL_DEVSRC_KVER}"
RREPLACES:${PN} += "${PN}"
RREPLACES:${PN}-dev += "${PN}-dev"
RREPLACES:${PN}-dbg += "${PN}-dbg"

python do_package:prepend() {
    if not d.getVar('KERNEL_VERSION'):
        bb.fatal("kernel-devsrc: KERNEL_VERSION is unset, cannot name the package after its kernel")
}

# For version tracking, we create a .kernel-version file inside the package.
# Avocado can read this from /usr/src/kernel/.kernel-version to verify
# the kernel-devsrc matches the target kernel version.

do_install:append() {
    # Use the same kerneldir as the base recipe
    kerneldir=${D}${KERNEL_BUILD_ROOT}${KERNEL_VERSION}/build

    # Only proceed if kerneldir exists
    if [ ! -d "$kerneldir" ]; then
        bbwarn "kernel-devsrc-fix: kerneldir $kerneldir does not exist, skipping"
        return
    fi

    bbnote "kernel-devsrc-fix: Adding generated headers for out-of-tree module support"

    # Copy generated architecture-specific headers from the kernel build directory
    # These are created during kernel build and include asm/types.h for ARM64
    if [ -d "${B}/arch/${ARCH}/include/generated" ]; then
        mkdir -p $kerneldir/arch/${ARCH}/include/generated
        cp -a ${B}/arch/${ARCH}/include/generated/* $kerneldir/arch/${ARCH}/include/generated/
        # kbuild leaves .<file>.h.cmd shadow files next to each generated header.
        # They record literal make command lines containing ${TMPDIR}, which the
        # wrynose `buildpaths` QA check (now fatal) rejects. They're only used
        # for in-tree incremental rebuilds — external module builds don't need
        # them. Upstream already deletes a few specific .cmd files (vdso-offsets);
        # this strips the rest under our generated/ copy.
        find $kerneldir/arch/${ARCH}/include/generated -type f -name '.*.cmd' -delete 2>/dev/null || :
        bbnote "kernel-devsrc-fix: Copied arch/${ARCH}/include/generated/ from build directory"
    else
        bbwarn "kernel-devsrc-fix: No generated headers found at ${B}/arch/${ARCH}/include/generated"
    fi

    # Create include/asm symlink if it doesn't exist
    # Points to architecture-specific asm headers (needed for #include <asm/...>)
    if [ ! -e "$kerneldir/include/asm" ] && [ -d "$kerneldir/arch/${ARCH}/include/asm" ]; then
        ln -sf ../arch/${ARCH}/include/asm $kerneldir/include/asm
        bbnote "kernel-devsrc-fix: Created include/asm symlink"
    fi

    # Create include/uapi/asm symlink
    # ARM64's asm/types.h is at arch/arm64/include/generated/uapi/asm/types.h
    if [ ! -e "$kerneldir/include/uapi/asm" ]; then
        mkdir -p $kerneldir/include/uapi
        if [ -d "$kerneldir/arch/${ARCH}/include/generated/uapi/asm" ]; then
            ln -sf ../../arch/${ARCH}/include/generated/uapi/asm $kerneldir/include/uapi/asm
            bbnote "kernel-devsrc-fix: Created include/uapi/asm symlink -> generated/uapi/asm"
        elif [ -d "$kerneldir/arch/${ARCH}/include/uapi/asm" ]; then
            ln -sf ../../arch/${ARCH}/include/uapi/asm $kerneldir/include/uapi/asm
            bbnote "kernel-devsrc-fix: Created include/uapi/asm symlink -> uapi/asm"
        fi
    fi

    # Create include/generated/asm symlink for generated asm headers
    if [ ! -e "$kerneldir/include/generated/asm" ] && [ -d "$kerneldir/arch/${ARCH}/include/generated/asm" ]; then
        mkdir -p $kerneldir/include/generated
        ln -sf ../../arch/${ARCH}/include/generated/asm $kerneldir/include/generated/asm
        bbnote "kernel-devsrc-fix: Created include/generated/asm symlink"
    fi

    # Fix ownership - cp -a preserves ownership from build user, but packaging
    # expects root:root. The base recipe does chown before our append runs.
    chown -R root:root $kerneldir/arch/${ARCH}/include/generated 2>/dev/null || :

    # Fix: upstream kernel-devsrc.bb uses explicit file globs for VDSO sources
    # (e.g., *gettimeofday.*, sigreturn.S, note.S) that miss files added in
    # newer kernels. Kernel 6.11+ added vgetrandom to the VDSO, requiring
    # vgetrandom.c and vgetrandom-chacha.S. The vdso_prepare target runs during
    # modules_prepare on arm64 (and powerpc, loongarch, s390, parisc) and needs
    # all VDSO source files to compile. Copy the complete VDSO directory to
    # future-proof against new additions — matching the approach riscv already
    # uses in the upstream recipe.
    if [ -d "${S}/arch/${ARCH}/kernel/vdso" ]; then
        (
            cd ${S}
            cp -a --parents arch/${ARCH}/kernel/vdso/* $kerneldir/ 2>/dev/null || :
        )
        chown -R root:root $kerneldir/arch/${ARCH}/kernel/vdso 2>/dev/null || :
        bbnote "kernel-devsrc-fix: Copied complete ${ARCH} VDSO sources for modules_prepare"
    fi

    # Create a version metadata file for Avocado to read.
    # We can't set PV=${KERNEL_VERSION} because it's not available at parse time,
    # but we can embed it in the package for runtime version checking.
    echo "${KERNEL_VERSION}" > $kerneldir/.kernel-version
    chown root:root $kerneldir/.kernel-version
}
