FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

# Kernel 7.2 vendored for avocado-amd-x86-64-v4 (linux-yocto_7.2.bb) uses
# upstream Kconfig's conditional-dependency syntax ("depends on X if Y",
# Linux commit 76df6815dab7, first released in v7.0). The pinned
# kern-tools-native SRCREV (a4a362d9f4f0abc8ab145a8673166b9bd875731a)
# predates yocto-kernel-tools' fix for it, so do_kernel_configcheck aborts:
#
#   kconfiglib.KconfigError: drivers/usb/cdns3/Kconfig:5: error: couldn't
#   parse 'depends on USB if !USB_GADGET': extra tokens at end of line
#
# Backport yocto-kernel-tools commit b5f008535c857153b4d69bd456913cf0cd6194a4
# ("Kconfiglib: support conditional 'depends on X if Y' dependencies",
# upstream master as of 2026-06-18) as a single patch rather than bumping
# SRCREV wholesale - master also carries two unrelated commits (a Kconfiglib
# self-test addition and a kgit bucket-classification update for kernel 6.19)
# this change has no reason to pull in.
SRC_URI:append = " file://0001-Kconfiglib-support-conditional-depends-on-X-if-Y-dep.patch"
