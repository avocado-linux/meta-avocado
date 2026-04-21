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

# Override upstream oot_update_rprovides so OOT shim packages emit
# kernel-version-qualified RCONFLICTS/RREPLACES. Upstream emits unqualified
# "kernel-module-<X>" Conflicts/Replaces, which collide across kernel versions
# when multiple kernels' RPMs coexist in Avocado's rolling $releasever feeds
# (solver sees parallel-installable shims as mutually exclusive).
#
# The unqualified RPROVIDES are preserved — install-by-name paths (both dnf
# user commands and avocado-bsp RDEPENDS that reference bare module names)
# depend on them. This mirrors kernel-module-split.bbclass, which emits both
# unqualified and versioned Provides for in-tree modules.
python oot_update_rprovides() {
    import re
    override_drivers = set(d.getVar('TEGRA_OOT_REPLACEMENT_DRIVERS').split())
    pkg_prefix = d.getVar('KERNEL_MODULE_PACKAGE_PREFIX')
    if not pkg_prefix:
        return
    kernel_version = d.getVar('KERNEL_VERSION')
    module_prefix = pkg_prefix + (d.getVar('KERNEL_PACKAGE_NAME') or 'kernel') + '-module-'
    virt_module_prefix = (d.getVar('KERNEL_PACKAGE_NAME') or 'kernel') + '-module-'
    module_suffix = d.getVar('KERNEL_MODULE_PACKAGE_SUFFIX')
    packages = d.getVar('PACKAGES').split()
    enumerated_drivers = set(d.getVar('TEGRA_OOT_ALL_DRIVER_PACKAGES').split())
    pkg_pat = re.compile(re.escape(module_prefix) + r'(.*)' + re.escape(module_suffix))
    for oot_pkg in d.getVar('PACKAGES').split():
        m = pkg_pat.match(oot_pkg)
        if m is None:
            continue
        basename = m.group(1)
        bb.debug(1, "Processing: %s (driver %s)" % (oot_pkg, basename))
        if module_prefix + basename not in enumerated_drivers:
            bb.warn("out-of-tree kernel module %s not listed in TEGRA_OOT_ALL_DRIVER_PACKAGES" % (module_prefix + basename))
        unprefixed = oot_pkg[len(pkg_prefix):]
        virt_unqual = virt_module_prefix + basename
        unprefixed_ver = unprefixed + '-' + kernel_version
        virt_ver = virt_unqual + '-' + kernel_version
        # Keep unqualified Provides so install-by-name still resolves; add
        # versioned forms so the solver can distinguish kernel versions.
        newprovides = ' '.join([unprefixed, virt_unqual, unprefixed_ver, virt_ver])
        bb.note("Adding %s to RPROVIDES:%s" % (newprovides, oot_pkg))
        d.appendVar('RPROVIDES:' + oot_pkg, ' ' + newprovides)
        if basename in override_drivers:
            # Scope conflicts/replaces by kernel version so a shim only
            # displaces the in-tree module of its own kernel, not a co-resident
            # module for a different kernel version in the same feed.
            versioned_only = unprefixed_ver + ' ' + virt_ver
            d.setVar('RREPLACES:' + oot_pkg, versioned_only)
            d.setVar('RCONFLICTS:' + oot_pkg, versioned_only)
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
