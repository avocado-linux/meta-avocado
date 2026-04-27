FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

SRC_URI:remove:grinn-astra-platform = " \
	file://${MACHINE}.dts;subdir=${DT_DIR} \
"

SRC_URI:append:grinn-astra-platform = " \
	file://${GRINN_MACHINE}.dts;subdir=${DT_DIR} \
	file://avocado.cfg \
"

CMDLINE_EMMC_BOOT:avocado = "console=ttyS0,115200 rootwait rootfstype=erofs"

do_deploy:prepend() {
	# Force yocto to use syna-mkbootimg instead of mkbootimg from android-tools-native, which is not compatible
	mkbootimg() {
		syna-mkbootimg "$@"
	}
}

require recipes-kernel/linux/avocado-kernel-modules-packagegroup.inc
