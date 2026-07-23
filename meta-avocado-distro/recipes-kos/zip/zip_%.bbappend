# Keep the base recipe's native variant (this append previously clobbered
# BBCLASSEXTEND with nativesdk-only, dropping zip-native): tk_9.0.3 DEPENDS on
# zip-native, which the tegra AI stack pulls transitively
# (holoscan/pytorch -> ... -> python3-pillow -> tk). Provide both.
BBCLASSEXTEND = "native nativesdk"
