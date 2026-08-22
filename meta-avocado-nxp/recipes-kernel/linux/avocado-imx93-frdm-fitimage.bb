SUMMARY = "avocado-imx93-frdm kernel as a FIT image bundling the initramfs"
DESCRIPTION = "Bundles this machine's kernel, device tree and initramfs into \
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

# Set the version of this recipe to the version of the included kernel
# (without taking the long way around via PV), matching linux-yocto-fitimage.bb.
PKGV = "${@get_kernelversion_file("${STAGING_KERNEL_BUILDDIR}")}"

# INITRAMFS_IMAGE/INITRAMFS_IMAGE_BUNDLE are set in avocado-imx93-frdm.conf,
# not here: kernel.bbclass's early anonymous python (which decides whether to
# addtask do_bundle_initramfs on linux-imx at all) needs to see them before
# ANY recipe parses, and linux-imx and this recipe are two different
# datastores either way. The initramfs ends up folded into vmlinux.initramfs
# by linux-imx's own do_bundle_initramfs, not as a separate FIT ramdisk node -
# it's what unlocks /var and brings up the fTPM, so its integrity matters
# most here (design decision: one signature over kernel+dtb+initramfs
# together, not per-file), and this way it's covered by the same
# kernel-1 image hash/signature rather than a second, independent one.
