# We want to use the config and dts defined in the machine file
SRC_URI:remove:grinn-astra-platform = " \
	file://${MACHINE}.dts \
	file://${MACHINE}_defconfig \
"

SRC_URI:append:grinn-astra-platform = " \
	file://${GRINN_MACHINE}.dts \
	file://${GRINN_MACHINE}_defconfig \
"

do_configure:prepend:grinn-astra-1680-platform() {
	# Ensure that meta-grinn-astra is not failing due to a dependency to MACHINE
	# The following error would appear:
	# cp: cannot stat '/work/build/tmp/work/avocado_grinn_astra_1680_sbc-avocado-linux/syna-u-boot/2025.01+git/avocado-grinn-astra-1680-sbc.dts': No such file or directory
	cp ${UNPACKDIR}/${GRINN_MACHINE}.dts ${UNPACKDIR}/${MACHINE}.dts
	cp ${UNPACKDIR}/${GRINN_MACHINE}_defconfig ${UNPACKDIR}/${MACHINE}_defconfig

	# It get even worse, because __anonymous magic is used, we can't force UBOOT_DEFCONFIG and therefore we always end in madness...
	cp ${UNPACKDIR}/${GRINN_MACHINE}_defconfig "${S}/boot/u-boot/configs/${MACHINE_NAME}_suboot_defconfig"
}
