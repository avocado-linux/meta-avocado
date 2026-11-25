# meta-openembedded splits chronyc into its own package with no dependency from chrony, so declaring chrony
# yields a daemon with no client. RDEPENDS, not RRECOMMENDS: a package manager without weak dependencies skips those.
RDEPENDS:${PN}:append = " chronyc"
