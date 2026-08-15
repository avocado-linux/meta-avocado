# Pull the NVIDIA device-tree overlay delivery hook into the SDK target
# sysroot alongside kernel-devsrc, so the avocado CLI finds it at
# $OECORE_TARGET_SYSROOT/usr/libexec/avocado/device-tree-overlay-deliver when
# building a runtime that declares device-tree overlays. This bbappend is only
# parsed for builds that include meta-avocado-nvidia, so non-Jetson builds
# never reference the NVIDIA-only recipe.
SDK_SYSROOT_DEPENDS:append = " avocado-dtc-overlay-deliver"
