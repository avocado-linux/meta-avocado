# mali-imx's anonymous python adds RPROVIDES/RREPLACES/RCONFLICTS for the
# Debian-style GL package names using "${PN}-<lib>" as the variable key.
# Anonymous functions run after bitbake's key expansion, so those keys never
# resolve and the parse cache carries no runtime provider for libgles2 & co.
# Anything that RDEPENDS on the plain names (wpewebkit, cog) then fails with
# "Nothing RPROVIDES 'libgles2'". Restate them with literal keys; harmless
# once the vendor recipe is fixed. Single-driver mode only, like upstream.
python __anonymous() {
    if d.getVar('IMX_MALI_DUAL_DRIVER') == '1':
        return
    pn = d.getVar('PN')
    for p in (("libegl",   "libegl1"),
              ("libgbm",   "libgbm1"),
              ("libgles1", "libglesv1-cm1"),
              ("libgles2", "libglesv2-2"),
              ("libgles3",)):
        pkgs = " ".join(p)
        for var in ("RREPLACES", "RPROVIDES", "RCONFLICTS"):
            d.appendVar("%s:%s-%s" % (var, pn, p[0]), " " + pkgs)
            d.appendVar("%s:%s-%s-dev" % (var, pn, p[0]), " " + p[0] + "-dev")
}
