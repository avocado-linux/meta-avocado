# triton-backend ships libtriton-backend-cuda-utils.a in ${PN}-staticdev, and
# the static archive embeds TMPDIR object paths. The upstream recipe (OE4T
# meta-tegra-community, all branches through whinlatter / wip-l4t-r39.2.0 as of
# our pin) skips the buildpaths QA only for ${PN}-dev, not ${PN}-staticdev --
# stock distros treat buildpaths as a warning, but the avocado distro treats it
# as fatal, so the gap fails our build. Extend the same skip to -staticdev.
# TODO: upstream this alongside the existing INSANE_SKIP:${PN}-dev.
INSANE_SKIP:${PN}-staticdev += "buildpaths"
