# Fix kernel-devsrc package to include generated headers needed for
# out-of-tree kernel module compilation.
#
# ARM64 (and some other architectures) have asm/types.h as a generated header
# in arch/${ARCH}/include/generated/, not in the kernel source tree.
# The upstream kernel-devsrc.bb copies arch/${ARCH}/include from ${S} (source)
# but misses the generated headers from ${B} (build directory).
#
# This bbappend copies the generated headers and creates necessary symlinks.

# Note: We cannot set PV = "${KERNEL_VERSION}" because KERNEL_VERSION is
# determined at runtime (during kernel build), not at parse time. This would
# make the recipe non-deterministic and cause basehash errors.
#
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

    # Create a version metadata file for Avocado to read.
    # We can't set PV=${KERNEL_VERSION} because it's not available at parse time,
    # but we can embed it in the package for runtime version checking.
    echo "${KERNEL_VERSION}" > $kerneldir/.kernel-version
    chown root:root $kerneldir/.kernel-version
}
