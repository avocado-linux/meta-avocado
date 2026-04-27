# Cross-mc kernel-feed assembly on the avocado-distro meta-target.
#
# Activated by feature ymls (kas/feature/multi-kernel-<family>.yml) which
# `INHERIT += "avocado-multikernel"` and set AVOCADO_MULTIKERNEL_MC_RECIPES
# to a space-separated list of "<mc>:<recipe>" pairs identifying the
# alternate-kernel recipes that should be built and merged into the
# unified feed.
#
# Two effects on the avocado-distro recipe:
#   1. do_multikernel_merge[mcdepends] is synthesized from the variable,
#      so `bitbake avocado-distro` transitively builds each alt-mc recipe
#      (no caller-side --target mc:... flags needed).
#   2. do_multikernel_merge runs after do_configure and before do_compile
#      (which calls avocado-repo-map's do_create_repo_map). It copies each
#      ${TOPDIR}/tmp-${mc}/deploy/ tree into ${DEPLOY_DIR}. The repo-map
#      task then sees a unified arch tree, the per-recipe Pulp manifests
#      from every mc are unified into ${DEPLOY_DIR}/pulp-uploads/, and
#      the Tekton CI task (which only reads from the default mc's
#      tmp/deploy/) sees everything without any per-target awareness.
#
# The bbclass is intended to be inherited globally (via INHERIT in
# local_conf_header) but only takes effect on the avocado-distro recipe;
# every other recipe gets a noexec'd do_multikernel_merge stub.

python () {
    if d.getVar('PN') != 'avocado-distro':
        return
    pairs = (d.getVar('AVOCADO_MULTIKERNEL_MC_RECIPES') or '').split()
    mcdeps = []
    for pair in pairs:
        mc, _, recipe = pair.partition(':')
        if not recipe:
            bb.warn("avocado-multikernel: malformed entry '%s' "
                    "(want '<mc>:<recipe>')" % pair)
            continue
        mcdeps.append("mc::%s:%s:do_build" % (mc, recipe))
    if not mcdeps:
        return
    d.delVarFlag('do_multikernel_merge', 'noexec')
    d.appendVarFlag('do_multikernel_merge', 'mcdepends', ' ' + ' '.join(mcdeps))
}

do_multikernel_merge[noexec] = "1"
do_multikernel_merge[nostamp] = "1"
do_multikernel_merge() {
    for pair in ${AVOCADO_MULTIKERNEL_MC_RECIPES}; do
        mc="${pair%%:*}"
        src="${TOPDIR}/tmp-${mc}/deploy/"
        if [ -d "${src}" ]; then
            bbnote "avocado-multikernel: merging alt-mc ${mc} deploy tree into ${DEPLOY_DIR}"
            cp -a "${src}/." "${DEPLOY_DIR}/"
        fi
    done
}
addtask multikernel_merge after do_configure before do_compile
