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
#      (which calls avocado-repo-map's do_create_repo_map). It copies only
#      the rpm/ and pulp-uploads/ subtrees from each alt-mc deploy dir into
#      ${DEPLOY_DIR}. spdx/ is intentionally excluded: both kernels produce
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
        for subdir in rpm pulp-uploads; do
            src="${base}/${subdir}"
            if [ -d "${src}" ]; then
                bbnote "avocado-multikernel: merging alt-mc ${mc} deploy/${subdir} into ${DEPLOY_DIR}/${subdir}"
                cp -a "${src}/." "${DEPLOY_DIR}/${subdir}/"
            fi
        done
    done
}
addtask multikernel_merge after do_configure before do_compile
