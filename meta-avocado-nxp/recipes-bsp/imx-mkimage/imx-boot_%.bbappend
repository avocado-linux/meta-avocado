# AHAB signing of the assembled imx-boot container when the ahab
# DISTRO_FEATURE is on (imx93-ahab-secure-boot-v2). Nothing else lives here:
# the imx95 SRCREV pins this file once carried were dropped with the wrynose
# vendor-layer repin.
require ${@ 'imx-boot-ahab-sign.inc' if bb.utils.contains('DISTRO_FEATURES', 'ahab', True, False, d) else ''}
