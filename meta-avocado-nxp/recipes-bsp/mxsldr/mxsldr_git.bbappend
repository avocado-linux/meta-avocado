# source.denx.de no longer serves mxsldr, so every SDK build that pulls
# nativesdk-mxsldr fails in do_fetch. The project moved to
# github.com/Freescale/mxsldr; the pinned SRCREV is there unchanged.
#
# meta-freescale fixed the recipe upstream (871c760ed6 "mxsldr: Fix SRC_URI
# URL", on master and wrynose); the pinned meta-freescale predates it. Drop
# this on the next meta-freescale repin.
SRC_URI:remove = "git://source.denx.de/denx/mxsldr.git;branch=master;protocol=https"
SRC_URI:prepend = "git://github.com/Freescale/mxsldr.git;branch=master;protocol=https "
