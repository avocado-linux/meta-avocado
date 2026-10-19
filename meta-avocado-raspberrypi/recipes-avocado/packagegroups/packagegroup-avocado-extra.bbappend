# Pull the Raspberry Pi device-tree overlay delivery hook into the SDK target
# sysroot alongside kernel-devsrc, so the avocado CLI finds it at
# $OECORE_TARGET_SYSROOT/usr/libexec/avocado/device-tree-overlay-deliver when
# building a runtime that declares device-tree overlays. This bbappend is only
# parsed for builds that include meta-avocado-raspberrypi, so non-RPi builds
# never reference the RPi-only recipe.
SDK_SYSROOT_DEPENDS:append = " avocado-dtc-overlay-deliver"
