# The mali-imx.inc anonymous Python function stores RPROVIDES keys with
# literal "${PN}" (e.g. "RPROVIDES:${PN}-libegl"). BitBake's expandKeys()
# runs before __anonymous(), so those keys are never expanded and the
# runtime dependency resolver cannot find them. Re-declare them here using
# standard BitBake syntax so expandKeys() can process them correctly.
RPROVIDES:mali-imx-libegl   += "libegl libegl1"
RPROVIDES:mali-imx-libgbm   += "libgbm libgbm1"
RPROVIDES:mali-imx-libgles1 += "libgles1 libglesv1-cm1"
RPROVIDES:mali-imx-libgles2 += "libgles2 libglesv2-2"
RPROVIDES:mali-imx-libgles3 += "libgles3"
