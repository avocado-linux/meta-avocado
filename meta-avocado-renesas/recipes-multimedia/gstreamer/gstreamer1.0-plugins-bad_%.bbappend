# meta-rzv2n appends PACKAGECONFIG "bayer", which wrynose's 1.28 recipe
# doesn't define (fatal invalid-packageconfig). The bayer plugin has no
# dependencies and builds by default, so gstreamer1.0-plugins-bad-bayer
# still exists without it.
PACKAGECONFIG:remove:rzv2n-sr-som = "bayer"
