# Pull the QEMU device-tree overlay delivery hook into the SDK target sysroot
# alongside kernel-devsrc, so the avocado CLI finds it at
# $OECORE_TARGET_SYSROOT/usr/libexec/avocado/device-tree-overlay-deliver when
# building a qemu runtime that declares device-tree overlays. This bbappend is
# only parsed for builds that include meta-avocado-qemu, so non-qemu builds
# never reference the qemu recipe.
#
# Machine-scoped, not layer-wide: this layer also owns avocado-qemux86-64, which
# boots via zboot and has no device tree anywhere in the chain. Installed there,
# the hook would compile the .dtbo, match bzImage as the "boot" kernel, append
# the overlay to the FAT and set claimed_by - so every gate passes and the build
# exits 0 having shipped a file nothing will ever read. Leaving x86 without the
# hook makes the CLI's undelivered check fail the build instead, which is the
# honest answer to asking for a device-tree overlay on a machine that has no
# device tree.
SDK_SYSROOT_DEPENDS:append:avocado-qemuarm64 = " avocado-dtc-overlay-deliver"
