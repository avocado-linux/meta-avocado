# The prebuilt GPU binaries are shipped under the poky vendor tuple
# (aarch64-poky-linux) regardless of the distro name. Override the paths
# so they resolve correctly when building with the avocado distro.
PREBUILT_LIBS = "sysroot/linux-baseline/data/gfx_prebuilt/mali/${DISPLAY_SERVER}/${SYNAMACH}/aarch64-poky-linux/lib/"
PREBUILT_BINS = "sysroot/linux-baseline/data/gfx_prebuilt/mali/${DISPLAY_SERVER}/${SYNAMACH}/aarch64-poky-linux/bin/"
