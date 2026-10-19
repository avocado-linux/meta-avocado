FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI:append = " \
  file://avocado-core.cfg \
  file://avocado-extra.cfg \
"

SRC_URI:append:reterminal = " file://reterminal.cfg"
SRC_URI:append:reterminal-dm = " file://reterminal.cfg"

inherit avocado-kernel-feed
inherit avocado-kernel-builtin-provides
require recipes-kernel/linux/avocado-kernel-modules-packagegroup.inc

# encrypted-var in the initramfs. linux-raspberrypi already builds dm-crypt and
# its crypto as modules on both feed kernels, so the kernel config is left
# alone: forcing them =y (avocado-security-kernel.inc) made libaes built in
# while the feed's kernel-module-libaes kept shipping, and hci_uart's module
# chain then failed with "exports duplicate symbol" - Bluetooth never came up.
# cryptsetup-var.sh modprobes dm-crypt; cryptsetup opens keyslots through the
# kernel's userspace crypto API (af-alg). Versioned so dnf takes this
# kernel's modules in the multi-kernel feed.
RDEPENDS:packagegroup-avocado-initramfs-modules:append = " \
    kernel-module-dm-mod-${KERNEL_VERSION} \
    kernel-module-dm-crypt-${KERNEL_VERSION} \
    kernel-module-af-alg-${KERNEL_VERSION} \
    kernel-module-algif-skcipher-${KERNEL_VERSION} \
    kernel-module-algif-hash-${KERNEL_VERSION} \
    kernel-module-aes-ce-blk-${KERNEL_VERSION} \
    kernel-module-aes-ce-cipher-${KERNEL_VERSION} \
"

# The boot partition takes its device trees from the same kernel as its Image
# (avocado-build-rpi stages both from the rootfs /boot), so the image package
# brings its own trees: a project pinned to a non-default kernel otherwise
# boots that kernel on the default kernel's trees.
RDEPENDS:${KERNEL_PACKAGE_NAME}-image:append = " ${KERNEL_PACKAGE_NAME}-devicetree"

