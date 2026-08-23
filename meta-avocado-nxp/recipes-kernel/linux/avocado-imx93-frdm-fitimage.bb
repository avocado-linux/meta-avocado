SUMMARY = "avocado-imx93-frdm kernel, device tree and initramfs as one FIT image"
DESCRIPTION = "Carries this machine's kernel, device tree and initramfs in \
a single FIT image via OE-core's kernel-fit-image mechanism, so U-Boot boots \
one container instead of three discrete files - signed when the verified-boot \
feature is selected, unsigned otherwise (see avocado-imx93-frdm.conf for the \
UBOOT_SIGN_* gate both this recipe and u-boot-imx read). kernel-fitimage.bbclass, \
the mechanism this was originally designed against, does not exist in this \
oe-core release - it was replaced by kernel-fit-image.bbclass, used as its own \
dedicated recipe depending on virtual/kernel:do_deploy rather than something \
inherited into the kernel recipe itself. This recipe mirrors oe-core's own \
meta/recipes-kernel/linux/linux-yocto-fitimage.bb, scoped to this machine."
SECTION = "kernel"

LICENSE = "GPL-2.0-with-Linux-syscall-note"
LIC_FILES_CHKSUM = "file://${COREBASE}/meta/files/common-licenses/GPL-2.0-with-Linux-syscall-note;md5=0bad96c422c41c3a94009dcfe1bff992"

COMPATIBLE_MACHINE = "avocado-imx93-frdm"

inherit linux-kernel-base kernel-fit-image

# kernel-fit-image.bbclass contributes only u-boot-tools-native, dtc-native and
# (when FIT_GENERATE_KEYS is "1", which it is not here) kernel-signing-keys-native,
# so nothing otherwise orders sb-keys' key generation before this recipe's signing
# step. The u-boot bbappend takes its own sb-keys dependency, but that edge is on
# u-boot's graph, not this one: `bitbake avocado-imx93-frdm-fitimage` on a tree
# with no keys yet has no path to generating them and dies in oe/fitimage.py's
# run_mkimage_sign. A build tree that already holds FIT.crt from an earlier run
# hides this completely, which is why it survived two full builds and a hardware
# pass. Gated on the feature because an unsigned FIT needs no key at all.
DEPENDS += "${@bb.utils.contains('DISTRO_FEATURES', 'verified-boot', 'sb-keys', '', d)}"

# Set the version of this recipe to the version of the included kernel
# (without taking the long way around via PV), matching linux-yocto-fitimage.bb.
PKGV = "${@get_kernelversion_file("${STAGING_KERNEL_BUILDDIR}")}"

# INITRAMFS_IMAGE comes from conf/distro/avocado.conf and the bundling
# decision is left at that file's default of "0" - see the comment in
# avocado-imx93-frdm.conf for why this machine does not override it.
#
# So the initramfs arrives as its own ramdisk-1 node emitted by
# kernel-fit-image.bbclass, carrying its own hash, and oe/fitimage.py adds
# "ramdisk" to the configuration node's signed entries next to "kernel" and
# "fdt". One signature over the whole configuration still covers kernel, dtb
# and initramfs together, which is the design property that matters: the
# initramfs unlocks /var and brings up the fTPM, so it must not be
# substitutable independently of the kernel it boots with.
