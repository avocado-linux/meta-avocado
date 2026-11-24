FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI:append = " \
  file://avocado-core.cfg \
  file://avocado-extra.cfg \
"

# DWARF for the kernel CVE filter (sbom-cve-check, see meta-avocado-sbom/README).
# linux-raspberrypi never reads KERNEL_EXTRA_FEATURES, which only the
# linux-yocto recipes consume, so the debug feature the filter needs arrives as
# a config fragment, on the switch avocado-kernel-feed uses for linux-yocto.
SRC_URI:append = " ${@'file://avocado-cve-debug.cfg' if d.getVar('AVOCADO_KERNEL_DEBUGINFO') == '1' else ''}"

# The defconfigs install modules as .ko.xz, which OE-core neither splits nor
# strips: their DWARF would ship and their sources would be missing from the
# compiled-source list, so a CVE in a module would read as not compiled.
# Unpack them in PKGD for the split and compress them again after it, with
# the kernel's own xz options. PKGD is a copy of D, so D, and the deploy
# modules tarball made from it, keep .ko.xz.
PACKAGE_PREPROCESS_FUNCS += "avocado_unpack_modules"
avocado_unpack_modules() {
	if [ "${AVOCADO_KERNEL_DEBUGINFO}" = "1" ]; then
		find ${PKGD}${nonarch_base_libdir}/modules -name '*.ko.xz' -exec xz -d {} +
	fi
}

PACKAGESPLITFUNCS:prepend = "avocado_recompress_modules "
avocado_recompress_modules() {
	if [ "${AVOCADO_KERNEL_DEBUGINFO}" = "1" ]; then
		find ${PKGD}${nonarch_base_libdir}/modules -name '*.ko' ! -path '*/.debug/*' \
			-exec xz --check=crc32 --lzma2=dict=1MiB {} +
	fi
}

SRC_URI:append:reterminal = " file://reterminal.cfg"
SRC_URI:append:reterminal-dm = " file://reterminal.cfg"

inherit avocado-kernel-feed
inherit avocado-kernel-builtin-provides
require recipes-kernel/linux/avocado-kernel-modules-packagegroup.inc

# The boot partition takes its device trees from the same kernel as its Image
# (avocado-build-rpi stages both from the rootfs /boot), so the image package
# brings its own trees: a project pinned to a non-default kernel otherwise
# boots that kernel on the default kernel's trees.
RDEPENDS:${KERNEL_PACKAGE_NAME}-image:append = " ${KERNEL_PACKAGE_NAME}-devicetree"
