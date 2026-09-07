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
#      deploy dir it merges into ${DEPLOY_DIR}: from rpm/ exactly the RPMs the
#      named alt-mc recipes produced, plus pulp-uploads/ additively. spdx/ is
#      intentionally excluded: both kernels produce SPDX files with the same
#      unversioned package names (kernel.spdx.json etc.), so merging them into
#      the shared deploy area causes a "files already exist" collision in
#      do_create_spdx. Each mc's spdx/ stays in its own tmp-<mc>/deploy/spdx/
#      and is collected separately if needed.
#
# This affects the LOCAL feed only. Production needs no merge at all:
# avocado-pulp-upload.bbclass hooks do_package_write_rpm[postfuncs] per recipe
# and uploads into a Pulp repo keyed on release/channel + arch, not on TMPDIR,
# so every mc's RPMs reach the same repo on their own.

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
        recipe="${pair#*:}"
        base="${TOPDIR}/tmp-${mc}"

        # Only the named recipes' OWN RPMs may cross into the shared deploy/rpm.
        # Every other RPM the alt mc emits (base-files, systemd-conf,
        # shadow-securetty, the unversioned packagegroup-avocado-* ...) is a
        # shared MACHINE_ARCH build dep the default mc also owns under the same
        # NEVRA. Copying those lands sstate-unmanaged files in the shared
        # deploy/rpm and trips the "trying to install files into a shared area
        # when those files already exist / not matched to any task" guard the
        # next time the default mc runs do_package_write_rpm for that recipe.
        #
        # A skip-if-exists check is NOT sufficient on its own: bitbake's
        # stale-sstate prune (sstate_eventhandler_stalesstate, the "Removing N
        # stale sstate objects" pass) routinely empties exactly these common
        # RPMs from the default deploy/rpm on a kernel re-sign, so at merge time
        # the destination is momentarily absent and skip-if-exists wrongly
        # copies the alt's copy in.
        #
        # So take the set from the alt mc's own sstate manifest for that
        # recipe's do_package_write_rpm, which lists precisely the files that
        # task installed into DEPLOY_DIR_RPM. It is written on both the live and
        # the setscene path, it names nothing any other recipe owns, and it
        # depends solely on the alt mc's state -- never on the prunable default
        # deploy tree -- so it is immune to prune/ordering races.
        #
        # This replaces a heuristic that filtered rpm/ by "basename contains the
        # alt kernel's N.N.N", derived by sed from an rpm filename. That key only
        # separates the two kernels when they differ in upstream version, which
        # holds for Jetson (6.18 vs 6.8) and Raspberry Pi (6.12 vs 6.6) but not
        # for a stock/PREEMPT_RT pair built from one source tree, where both
        # reduce to the same N.N.N and the filter stops filtering. It also
        # dropped each alt kernel's kernel, kernel-dbg, kernel-dev and
        # kernel-vmlinux subpackages on families where it did work, since
        # kernel.bbclass never version-qualifies those four names.
        #
        # Corollary: a recipe whose NEVRA genuinely collides across mcs must not
        # be listed in AVOCADO_MULTIKERNEL_MC_RECIPES at all. kernel-devsrc is
        # the live example -- kernelsrc.bbclass sets its PKGV to
        # KERNEL_VERSION.split("-")[0], so two kernels off one source tree share
        # it -- which is why the qcom overlay lists only the kernel itself.
        # Plain $rpmroot, not ${rpmroot}: bitbake expands any ${...} it can
        # resolve before the shell sees the function, and a nested
        # ${src#${rpmroot}/} is not worth relying on it leaving alone.
        rpmroot="${base}/deploy/rpm"
        manifest="$(ls "${base}/sstate-control/manifest-"*"-${recipe}.package_write_rpm" 2>/dev/null | head -1)"
        if [ -z "${manifest}" ]; then
            bbwarn "avocado-multikernel: no package_write_rpm manifest for '${recipe}' under ${base}/sstate-control; skipping its rpm merge"
        else
            bbnote "avocado-multikernel: merging alt-mc ${mc} recipe ${recipe} rpms into ${DEPLOY_DIR}/rpm (from ${manifest})"
            while read -r src; do
                # The manifest also carries the directory it created; -f drops
                # that and any entry whose file is gone.
                [ -f "${src}" ] || continue
                case "${src}" in
                    "${base}/deploy/rpm/"*) ;;
                    *) continue ;;
                esac
                rel="${src#$rpmroot/}"
                dest="${DEPLOY_DIR}/rpm/${rel}"
                if [ -e "${dest}" ] || [ -L "${dest}" ]; then
                    bbnote "avocado-multikernel: skip (already present) rpm/${rel}"
                    continue
                fi
                mkdir -p "$(dirname "${dest}")"
                cp -a "${src}" "${dest}"
            done < "${manifest}"
        fi

        # pulp-uploads/ is a separate, non-sstate deploy area that does not hit
        # the shared-area guard, so it keeps the plain additive copy of the
        # whole tree. Merged once per pair; a second pair naming the same mc
        # just re-walks it and skips everything.
        src="${base}/deploy/pulp-uploads"
        if [ -d "${src}" ]; then
            bbnote "avocado-multikernel: merging alt-mc ${mc} deploy/pulp-uploads into ${DEPLOY_DIR}/pulp-uploads"
            ( cd "${src}" && find . -type f -o -type l ) | while read -r f; do
                dest="${DEPLOY_DIR}/pulp-uploads/${f}"
                if [ -e "${dest}" ] || [ -L "${dest}" ]; then
                    continue
                fi
                mkdir -p "$(dirname "${dest}")"
                cp -a "${src}/${f}" "${dest}"
            done
        fi
    done
}
addtask multikernel_merge after do_configure before do_compile
