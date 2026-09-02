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
#   3. Each alt-mc recipe's evidence — its cve-check results under
#      CVE_CHECK_DIR, its SPDX documents under DEPLOY_DIR_SPDX — into a <mc>/
#      subdirectory of each. Both mcs write the same recipe's results under one
#      filename (linux-raspberrypi_cve.json), so no additive copy keeps both,
#      and a subdirectory is a path no task installs — which is what keeps
#      do_create_spdx's "files already exist" shared-area guard out of it.
#      avocado-cve-report reads it back as alt_versions on the recipe.
#
#      ponytail: the opt-out and backport markers land there too, and
#      read_optouts/read_backports glob the top level only, so an alt-mc
#      backport reports "cve-check" evidence instead of "patch-file" —
#      understating what we patched. Neither kernel emits one today. The fix is
#      a (name, version) key, which reaches check_unscanned_declared too.

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

        # Both evidence trees are under ${DEPLOY_DIR}, and the alt mc's copy is
        # the same path with its own tmp tree in front, so each source is
        # derived by swapping that prefix. Unset or outside ${DEPLOY_DIR} - no
        # cve-check, no create-spdx, a relocated tree - is skipped.
        #
        # What to copy is decided from the alt mc's own output alone, like the
        # rpm filter below and for the same reason: this task runs before
        # do_compile, and do_compile is what depends on the rest of the distro,
        # so the default mc's cve/ and spdx/ are mostly absent here. Comparing
        # against them would copy a different set depending on when it ran.
        #
        # Read into shell variables first: bitbake expands a bare ${VAR} in a
        # shell function, but leaves ${VAR#...} alone - its expansion regexp
        # rejects the '#' - and emits neither name into the run script, so
        # stripping the prefix off the bitbake form yields "" every time.
        recipe="${pair#*:}"
        deploy_dir="${DEPLOY_DIR}"
        cve_dir="${CVE_CHECK_DIR}"
        spdx_dir="${DEPLOY_DIR_SPDX}"

        cve_rel="${cve_dir#$deploy_dir/}"
        if [ -n "${cve_dir}" ] && [ "${cve_rel}" != "${cve_dir}" ]; then
            for suffix in "" _cve.json _backports.json _optout.json; do
                src="${base}/${cve_rel}/${recipe}${suffix}"
                [ -f "${src}" ] || continue
                bbnote "avocado-multikernel: merging alt-mc ${mc} ${recipe}${suffix} into ${cve_dir}/${mc}"
                mkdir -p "${cve_dir}/${mc}"
                cp -a "${src}" "${cve_dir}/${mc}/${recipe}${suffix}"
            done
        fi

        spdx_rel="${spdx_dir#$deploy_dir/}"
        spdx_src="${base}/${spdx_rel}"
        if [ -n "${spdx_dir}" ] && \
           [ "${spdx_rel}" != "${spdx_dir}" ] && [ -d "${spdx_src}" ]; then
            # Selected on the document namespace, spdxdocs/<PN>-<uuid>, rather
            # than on the filename: that names the unversioned alias packages
            # too - package-kernel.spdx.json, -dbg, -dev, -vmlinux - whose RPMs
            # ship in the merged feed while their names carry no version. The
            # uuid is part of the pattern, or a recipe whose name prefixes
            # another's would claim its documents.
            #
            # grep -r does not follow symlinks met while recursing, which keeps
            # the by-hash/, by-namespace/ and by-spdxid-hash/ mirrors out.
            bbnote "avocado-multikernel: merging alt-mc ${mc} ${recipe} SPDX documents into ${spdx_dir}/${mc}"
            ( cd "${spdx_src}" && grep -rl --include='*.spdx.json' \
                  "spdxdocs/${recipe}-[0-9a-f]\{8\}-" . ) | while read -r f; do
                dest="${spdx_dir}/${mc}/${f}"
                mkdir -p "$(dirname "${dest}")"
                cp -a "${spdx_src}/${f}" "${dest}"
            done
        fi

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
        # version is derived from the alt mc's abiversioned kernel package
        # (e.g. kernel-6.6.63-v8-... -> 6.6.63); it tags every kernel RPM (PV
        # 6.6.63+git..., KERNEL_VERSION 6.6.63-v8) and none of the common NEVRAs
        # (base-files 3.0.14, packagegroup 1.0, shadow-securetty 4.6, ...).
        altkver="$(ls "${base}/rpm/"*/kernel-[0-9]*-v[0-9]*.rpm 2>/dev/null \
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
