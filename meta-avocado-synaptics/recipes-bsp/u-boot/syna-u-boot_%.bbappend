# meta-grinn-astra-bsp's bbappend adds file://${MACHINE}.dts to SRC_URI, which
# resolves to avocado-grinn-astra-1680-sbc.dts — a file that doesn't exist
# upstream. Swap it for the unprefixed Grinn name and copy it back under the
# MACHINE name so upstream's do_configure:append:grinn-astra-1680-platform
# (which references ${WORKDIR}/${MACHINE}.dts) keeps working.
SRC_URI:remove:grinn-astra-platform = "file://${MACHINE}.dts"
SRC_URI:append:grinn-astra-platform = " file://${GRINN_MACHINE}.dts"

do_configure:prepend:grinn-astra-1680-platform() {
	cp ${WORKDIR}/${GRINN_MACHINE}.dts ${WORKDIR}/${MACHINE}.dts
}
