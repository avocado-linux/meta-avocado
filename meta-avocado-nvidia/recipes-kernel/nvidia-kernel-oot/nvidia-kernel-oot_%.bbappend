# Extend the default -src package with Makefiles and build configuration files
# These help understand which source files and headers build which modules
# The default -src package from splitdebug only includes .c/.h files referenced in debug info
#
# Path for debug sources (used by splitdebug class)
DEBUG_SRC_PATH = "/usr/src/debug/${BPN}/${EXTENDPE}${PV}"

# Append build system files to the -src package
# These files document the module build structure and are useful for SDK users
FILES:${PN}-src += "\
    ${DEBUG_SRC_PATH}/**/Makefile \
    ${DEBUG_SRC_PATH}/**/Makefile.* \
    ${DEBUG_SRC_PATH}/**/*.mk \
    ${DEBUG_SRC_PATH}/**/*.tmk \
    ${DEBUG_SRC_PATH}/**/Kconfig* \
    ${DEBUG_SRC_PATH}/**/*.sources \
    ${DEBUG_SRC_PATH}/**/*.configs \
    ${DEBUG_SRC_PATH}/**/*.export \
"

do_install:append() {
    # Install Makefiles and build system files to the debug source directory
    # This allows SDK users to understand how modules are built
    install -d ${D}${DEBUG_SRC_PATH}
    (
        cd ${S}
        # Install all Makefiles and Makefile.* files (Makefile.sources, Makefile.configs, etc.)
        find . -name "Makefile" -o -name "Makefile.*" | while read -r file; do
            install -D -m 0644 "$file" "${D}${DEBUG_SRC_PATH}/$file"
        done

        # Install Kconfig files (kernel configuration)
        find . -name "Kconfig*" | while read -r file; do
            install -D -m 0644 "$file" "${D}${DEBUG_SRC_PATH}/$file"
        done

        # Install .mk files (make include files like utils.mk, version.mk)
        find . -name "*.mk" | while read -r file; do
            install -D -m 0644 "$file" "${D}${DEBUG_SRC_PATH}/$file"
        done

        # Install .tmk files (Tegra make files for nvethernetrm)
        find . -name "*.tmk" | while read -r file; do
            install -D -m 0644 "$file" "${D}${DEBUG_SRC_PATH}/$file"
        done

        # Install .sources files (source file lists like Makefile.sources)
        find . -name "*.sources" | while read -r file; do
            install -D -m 0644 "$file" "${D}${DEBUG_SRC_PATH}/$file"
        done

        # Install .configs files (build configuration files)
        find . -name "*.configs" | while read -r file; do
            install -D -m 0644 "$file" "${D}${DEBUG_SRC_PATH}/$file"
        done

        # Install .export files (symbol export definitions)
        find . -name "*.export" | while read -r file; do
            install -D -m 0644 "$file" "${D}${DEBUG_SRC_PATH}/$file"
        done
    )
}

# Override upstream oot_update_rprovides to drop the unqualified Provides +
# Conflicts it would otherwise add to each OOT shim. Under Path B's naming
# discipline (every kernel-family package identified by its full versioned
# PN `nv-kernel-module-<X>-<KERNEL_VERSION>`, no unqualified virtuals), OOT
# shims no longer need to publish `kernel-module-<X>` as a virtual or conflict
# on it — kernels coexist via installonlypkgs, and callers select modules
# explicitly by versioned name (via `{{ avocado.kernel.version }}` templating
# in BSP yamls or per-kernel packagegroups). Upstream's unqualified
# Provides/Conflicts are the source of all the cross-kernel tie-break pain in
# rolling multi-kernel feeds.
#
# The RDEPENDS-rewrite block from upstream is preserved: deps referring to
# in-tree modules via the `nv-` prefix convention still get the prefix
# stripped so they resolve against `kernel-module-split.bbclass`'s Provides
# on the in-tree package.
python oot_update_rprovides() {
    import re
    pkg_prefix = d.getVar('KERNEL_MODULE_PACKAGE_PREFIX')
    if not pkg_prefix:
        return
    module_prefix = pkg_prefix + (d.getVar('KERNEL_PACKAGE_NAME') or 'kernel') + '-module-'
    module_suffix = d.getVar('KERNEL_MODULE_PACKAGE_SUFFIX')
    packages = d.getVar('PACKAGES').split()
    pkg_pat = re.compile(re.escape(module_prefix) + r'(.*)' + re.escape(module_suffix))
    for oot_pkg in d.getVar('PACKAGES').split():
        m = pkg_pat.match(oot_pkg)
        if m is None:
            continue
        rdepstr = d.getVar('RDEPENDS:' + oot_pkg)
        if not rdepstr:
            continue
        rdeps = rdepstr.split()
        newdeps = []
        changed = False
        for dep in rdeps:
            if pkg_pat.match(dep) and dep not in packages:
                newdeps.append(dep[len(pkg_prefix):])
                changed = True
            else:
                newdeps.append(dep)
        if changed:
            newdepstr = ' '.join(newdeps)
            bb.note("Updating RDEPENDS:%s to %s" % (oot_pkg, newdepstr))
            d.setVar('RDEPENDS:' + oot_pkg, newdepstr)
}
