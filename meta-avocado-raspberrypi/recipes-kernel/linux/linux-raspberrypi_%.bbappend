FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI:append = " \
  file://avocado-core.cfg \
  file://avocado-extra.cfg \
"

# DWARF for the kernel CVE filter (do_kernel_cve_improve in meta-avocado-sbom).
# linux-raspberrypi never reads KERNEL_EXTRA_FEATURES, which only the
# linux-yocto recipes consume, so the debug feature the filter needs arrives as
# a config fragment. Tied to the variable that arms the filter, so a build that
# does not filter does not pay for a debug-info kernel.
SRC_URI:append = " ${@'file://avocado-cve-debug.cfg' if d.getVar('AVOCADO_CVE_KERNEL_VULNS_DIR') else ''}"

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
