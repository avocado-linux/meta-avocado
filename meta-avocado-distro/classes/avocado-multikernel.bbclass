# Cross-mc kernel-feed assembly on the avocado-distro meta-target.
#
# Inherited directly by avocado-distro.bb (`inherit avocado-multikernel`).
# Feature ymls (kas/feature/multi-kernel-<family>.yml) set
# AVOCADO_MULTIKERNEL_MC_RECIPES to a space-separated list of
# "<mc>:<recipe>" pairs identifying the alternate-kernel recipes that should
# be built and merged into the unified feed.
#
# Inheriting only in avocado-distro.bb (not via global INHERIT) keeps this
# class out of every other recipe's basehash, avoiding a full sstate miss
# when the class or AVOCADO_MULTIKERNEL_MC_RECIPES changes.
#
# Two effects on avocado-distro:
#   1. do_multikernel_merge[mcdepends] is synthesized from the variable,
#      so `bitbake avocado-distro` transitively builds each alt-mc recipe
#      (no caller-side --target mc:... flags needed).
#   2. do_multikernel_merge runs after do_configure and before do_compile
#      (which calls avocado-repo-map's do_create_repo_map). From each alt-mc
#      deploy dir it merges into ${DEPLOY_DIR}: from rpm/ only the alt kernel's
#      version-tagged RPMs (the genuinely-unique ones — shared MACHINE_ARCH
#      NEVRAs the default mc owns are skipped, else they collide with the
#      default mc's own do_package_write_rpm), plus pulp-uploads/ additively.
#      spdx/ is intentionally excluded: both kernels produce
#      SPDX files with the same unversioned package names (kernel.spdx.json
#      etc.), so merging them into the shared deploy area causes a "files
#      already exist" collision in do_create_spdx. Each mc's spdx/ stays in
#      its own tmp-<mc>/deploy/spdx/ and is collected separately if needed.

python () {
    pairs = (d.getVar('AVOCADO_MULTIKERNEL_MC_RECIPES') or '').split()
    mcdeps = []
    for pair in pairs:
        mc, _, recipe = pair.partition(':')
        if not recipe:
            bb.warn("avocado-multikernel: malformed entry '%s' "
                    "(want '<mc>:<recipe>')" % pair)
            continue
        mcdeps.append("mc::%s:%s:do_build" % (mc, recipe))
    if mcdeps:
        d.appendVarFlag('do_multikernel_merge', 'mcdepends', ' ' + ' '.join(mcdeps))
}

do_multikernel_merge[nostamp] = "1"
do_multikernel_merge() {
    for pair in ${AVOCADO_MULTIKERNEL_MC_RECIPES}; do
        mc="${pair%%:*}"
        base="${TOPDIR}/tmp-${mc}/deploy"

        # The alt mc's UNIQUE contribution is everything built against its
        # kernel version. Every other RPM it emits (base-files, systemd-conf,
        # shadow-securetty, the unversioned packagegroup-avocado-* ...) is a
        # shared MACHINE_ARCH build dep the default mc also owns as a
        # byte-identical NEVRA. Merging those lands sstate-unmanaged files in
        # the shared deploy/rpm and trips the "trying to install files into a
        # shared area when those files already exist / not matched to any task"
        # guard the next time the default mc runs do_package_write_rpm for that
        # recipe.
        #
        # A skip-if-exists check is NOT sufficient: bitbake's stale-sstate prune
        # (sstate_eventhandler_stalesstate, the "Removing N stale sstate objects"
        # pass) routinely empties exactly these common RPMs from the default
        # deploy/rpm on a kernel re-sign, so at merge time the destination is
        # momentarily absent and skip-if-exists wrongly copies the alt's copy in.
        #
        # So filter rpm/ to ONLY the alt kernel's version-tagged RPMs. This
        # depends solely on the alt mc's own output — never on the prunable
        # default deploy state — so it is immune to prune/ordering races. The
        # version is derived from the alt mc's kernel package
        # (e.g. kernel-6.6.63-v8-... -> 6.6.63); it tags every kernel RPM (PV
        # 6.6.63+git..., KERNEL_VERSION 6.6.63-v8) and none of the common NEVRAs
        # (base-files 3.0.14, packagegroup 1.0, shadow-securetty 4.6, ...).
        #
        # Match kernel-<N.N.N> without requiring an ABI suffix. The glob used to
        # be kernel-[0-9]*-v[0-9]*.rpm, which only matched the Raspberry Pi
        # shape (kernel-6.6.63-v8-...). Jetson's L4T kernel is
        # kernel-6.8.12-l4t-r39.2.0-1021.21-... with no -v<digit>, so the glob
        # matched nothing, altkver came back empty, and EVERY Jetson build
        # skipped the alt-mc merge with only a bbwarn -- leaving the L4T
        # kernel's RPMs out of the unified feed entirely. kernel-[0-9]* still
        # excludes kernel-module-*/kernel-image-*/kernel-devsrc-* (no digit
        # directly after "kernel-"), and the sed below takes only N.N.N, so
        # both naming shapes reduce to the same version key.
        altkver="$(ls "${base}/rpm/"*/kernel-[0-9]*.rpm 2>/dev/null \
                   | sed -nE 's#.*/kernel-([0-9]+\.[0-9]+\.[0-9]+)[-+].*#\1#p' \
                   | sort -u | head -1)"
        if [ -z "${altkver}" ]; then
            bbwarn "avocado-multikernel: could not derive a kernel version for mc '${mc}' from ${base}/rpm; skipping its merge"
            continue
        fi

        for subdir in rpm pulp-uploads; do
            src="${base}/${subdir}"
            if [ -d "${src}" ]; then
                bbnote "avocado-multikernel: merging alt-mc ${mc} kernel-${altkver} deploy/${subdir} into ${DEPLOY_DIR}/${subdir}"
                ( cd "${src}" && find . -type f -o -type l ) | while read -r f; do
                    # rpm/: only the alt kernel's own version-tagged RPMs are
                    # genuinely unique; skip every shared NEVRA the default mc
                    # owns. pulp-uploads/ is a separate, non-sstate deploy area
                    # that does not hit the shared-area guard, so it keeps the
                    # plain additive copy.
                    if [ "${subdir}" = "rpm" ]; then
                        case "$(basename "${f}")" in
                            *"${altkver}"*) : ;;
                            *) continue ;;
                        esac
                    fi
                    dest="${DEPLOY_DIR}/${subdir}/${f}"
                    if [ -e "${dest}" ] || [ -L "${dest}" ]; then
                        bbnote "avocado-multikernel: skip (already present) ${subdir}/${f}"
                        continue
                    fi
                    mkdir -p "$(dirname "${dest}")"
                    cp -a "${src}/${f}" "${dest}"
                done
            fi
        done
    done
}
addtask multikernel_merge after do_configure before do_compile
