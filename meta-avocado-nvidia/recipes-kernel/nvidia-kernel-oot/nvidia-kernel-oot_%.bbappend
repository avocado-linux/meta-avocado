# nvidia-kernel-oot is built in both the default mc (linux-yocto 6.6) and the
# jetson-l4t alt mc (linux-jammy-nvidia-tegra 5.15). Both builds share a single
# PR service. Each mc's build gets a distinct PR suffix (different KERNEL_VERSION
# → different task signature → independent PR counter). The shared PR service
# then has r0.0 and r0.1 for the same package name, causing do_packagedata_setscene
# to fire "version-going-backwards" when the lower-PR mc restores from sstate.
# This is structural — not a bug — so demote it from a fatal error to a warning.
ERROR_QA:remove = "version-going-backwards"
WARN_QA:append = " version-going-backwards"

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

# Override upstream oot_update_rprovides to strip the RCONFLICTS / RREPLACES
# from OOT shim packages. Upstream marks shims in TEGRA_OOT_REPLACEMENT_DRIVERS
# with an unqualified `Conflicts: kernel-module-<X>` so the shim displaces
# its in-tree counterpart; that works fine in a single-kernel image but
# explodes across kernel versions in a rolling feed (two different-named
# shims both Conflict with the same virtual name, so installing one refuses
# to coexist with the other already in @System).
#
# Kept from upstream:
#   - Unqualified `Provides: kernel-module-<X>` — BSP yamls and transitive
#     RDEPENDS reference modules by bare name; these Provides make that
#     resolve. OOT-only modules (capture-ivc, nvgpu, host1x-fence, etc.)
#     have no in-tree sibling, so nothing else can provide them.
#   - The RDEPENDS rewrite — deps referring to in-tree modules via the
#     `nv-` prefix convention get the prefix stripped.
#
# Dropped:
#   - Unqualified `Conflicts: kernel-module-<X>` on TEGRA_OOT_REPLACEMENT_DRIVERS.
#     Kernel-version coexistence is handled by installonlypkgs instead; when
#     multiple kernels provide the same unqualified virtual, dnf tie-breaks
#     by NVR (latest wins), which is the desired install-latest behavior.
#     Pin-to-older requires explicit `{{ avocado.kernel.version }}` templating
#     in the user's avocado.yaml.
python oot_update_rprovides() {
    import re
    pkg_prefix = d.getVar('KERNEL_MODULE_PACKAGE_PREFIX')
    if not pkg_prefix:
        return
    module_prefix = pkg_prefix + (d.getVar('KERNEL_PACKAGE_NAME') or 'kernel') + '-module-'
    virt_module_prefix = (d.getVar('KERNEL_PACKAGE_NAME') or 'kernel') + '-module-'
    module_suffix = d.getVar('KERNEL_MODULE_PACKAGE_SUFFIX')
    packages = d.getVar('PACKAGES').split()
    pkg_pat = re.compile(re.escape(module_prefix) + r'(.*)' + re.escape(module_suffix))
    for oot_pkg in d.getVar('PACKAGES').split():
        m = pkg_pat.match(oot_pkg)
        if m is None:
            continue
        basename = m.group(1)
        # Preserve upstream's unqualified Provides emission. Matches what
        # `oot_update_rprovides` emits by default — we just skip the
        # override_drivers Conflicts/Replaces block.
        newprovides = oot_pkg[len(pkg_prefix):] + " " + virt_module_prefix + basename
        d.appendVar('RPROVIDES:' + oot_pkg, ' ' + newprovides)
        # RDEPENDS rewrite (preserved from upstream).
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

# Emit supplementary OOT rootfs/initramfs module packagegroups. Symmetric
# with the kernel-owned packagegroups emitted from linux-jammy-nvidia-tegra_%.bbappend:
# each recipe contributes only what it builds, and the kernel-owned
# packagegroup RRECOMMENDS its OOT sibling so they install together when OOT
# is present. Empty RDEPENDS initially; populate as OOT modules become
# rootfs/initramfs-critical.
PACKAGES:append = " packagegroup-avocado-rootfs-modules-oot packagegroup-avocado-initramfs-modules-oot"
PKG:packagegroup-avocado-rootfs-modules-oot = "packagegroup-avocado-rootfs-modules-oot-${KERNEL_VERSION}"
PKG:packagegroup-avocado-initramfs-modules-oot = "packagegroup-avocado-initramfs-modules-oot-${KERNEL_VERSION}"
ALLOW_EMPTY:packagegroup-avocado-rootfs-modules-oot = "1"
ALLOW_EMPTY:packagegroup-avocado-initramfs-modules-oot = "1"
FILES:packagegroup-avocado-rootfs-modules-oot = ""
FILES:packagegroup-avocado-initramfs-modules-oot = ""
SUMMARY:packagegroup-avocado-rootfs-modules-oot = "OOT kernel modules pulled into the Avocado rootfs for kernel ${KERNEL_VERSION}"
SUMMARY:packagegroup-avocado-initramfs-modules-oot = "OOT kernel modules pulled into the Avocado initramfs for kernel ${KERNEL_VERSION}"
# nvidia-kernel-oot-base aggregates the OOT base drivers required for any
# Tegra rootfs running the L4T kernel (TEGRA_OOT_BASE_DRIVERS — host1x,
# nvgpu, tegra-bpmp, mc-utils, nvethernet, etc.). Pull it in via this
# kernel-version-qualified packagegroup rather than via meta-tegra's
# unconditional MACHINE_ESSENTIAL_EXTRA_RDEPENDS — the latter leaks 5.15
# OOT modules into 6.6 builds because nvidia-kernel-oot is only built by
# the alt mc (linux-jammy-nvidia-tegra 5.15). With this routing, the OOT
# modules only land in the rootfs when avocado-cli auto-appends this
# packagegroup, which only happens when an OOT-using kernel is pinned.
#
# packagegroup-avocado-rootfs.bbappend and packagegroup-core-boot.bbappend
# strip nvidia-kernel-oot-base from MACHINE_ESSENTIAL_EXTRA_RDEPENDS-
# expanded RDEPENDS, so this is now the only path.
RDEPENDS:packagegroup-avocado-rootfs-modules-oot = "nvidia-kernel-oot-base"
RDEPENDS:packagegroup-avocado-initramfs-modules-oot = ""
