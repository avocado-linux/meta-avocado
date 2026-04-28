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

# Rename kernel-devsrc to include KERNEL_VERSION so multiple kernel versions
# can coexist in a rolling feed without colliding on the unversioned package name.
PKG:${KERNEL_PACKAGE_NAME}-devsrc = "${KERNEL_PACKAGE_NAME}-devsrc-${KERNEL_VERSION}"
RPROVIDES:${KERNEL_PACKAGE_NAME}-devsrc += "kernel-devsrc kernel-devsrc-${KERNEL_VERSION}"

# avocado-cli kernel resolver contract: enumerates available kernels via
# `dnf repoquery --whatprovides 'avocado-kernel-*' --provides`.
RPROVIDES:${KERNEL_PACKAGE_NAME}-base += "avocado-kernel-${KERNEL_VERSION}"

require recipes-kernel/linux/avocado-kernel-modules-packagegroup.inc
