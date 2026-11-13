# meta-rz-bsp's out-of-tree module recipes (vspm, vspmif, mmngr, mmngrbuf, qos,
# ...) install their Module.symvers into the shared kernel source as
# include/<name>.symvers, for other modules to link against. kernel-devsrc copies
# that tree, so whether it carries those files depends on task order. When it
# does, the build fails QA: each symvers line holds the module's TMPDIR build
# path [buildpaths]. They are build-time links between vendor modules, never
# part of the kernel's own headers, so keep them out of the package.
do_install:append() {
    rm -f ${D}${KERNEL_BUILD_ROOT}${KERNEL_VERSION}/build/include/*.symvers
}
