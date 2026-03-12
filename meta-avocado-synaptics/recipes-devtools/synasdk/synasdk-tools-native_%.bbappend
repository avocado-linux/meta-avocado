do_install:append() {
    # Workaround conflict with android-tools-native, no idea why this is not an issue for the synaptics BSP
    mv ${D}${bindir}/mkbootimg ${D}${bindir}/syna-mkbootimg
}
