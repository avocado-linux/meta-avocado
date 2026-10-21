# Add-on feeds (docs/addon-feeds.md): packages built by their own multiconfig
# and published beside the base feed, never inside it, as
# target/<machine>-<addon> and sdk/<machine>-<addon>. A project opts in with
# `distro: { feeds: [<addon>] }`.
#
# A kas feature declares an add-on with:
#   BBMULTICONFIG += "<addon>"
#   AVOCADO_ADDON_FEEDS += "<addon>"
#   AVOCADO_ADDON_RECIPES[<addon>] = "<the recipes the add-on carries>"
# plus conf/multiconfig/<addon>.conf, which gives the multiconfig its own
# TMPDIR. The add-on's name is its multiconfig's name.
#
# Inheriting this class makes the meta-target build those recipes in the
# add-on's multiconfig, so `bitbake <meta-target>` produces the add-on too.
# Unlike avocado-multikernel, nothing crosses into this build's deploy tree:
# scripts/addon-feed-stage.sh selects the add-on's packages from the add-on's
# own TMPDIR and refuses any that would shadow a base package.
python () {
    multiconfigs = (d.getVar('BBMULTICONFIG') or '').split()
    deps = []
    for addon in (d.getVar('AVOCADO_ADDON_FEEDS') or '').split():
        if addon not in multiconfigs:
            bb.fatal("avocado-addon-feeds: AVOCADO_ADDON_FEEDS lists '%s' but BBMULTICONFIG "
                     "does not; an add-on is built by the multiconfig of the same name" % addon)
        recipes = (d.getVarFlag('AVOCADO_ADDON_RECIPES', addon) or '').split()
        if not recipes:
            bb.fatal("avocado-addon-feeds: AVOCADO_ADDON_RECIPES[%s] is empty" % addon)
        deps += ["mc::%s:%s:do_build" % (addon, r) for r in recipes]
    if deps:
        d.appendVarFlag('do_compile', 'mcdepends', ' ' + ' '.join(deps))
}
