DESCRIPTION = "Packagegroup for Raspberry Pi initramfs - extra packages needed for early boot"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

# Note: xhci-hcd, xhci-pci, usb-storage, and uas are built-in (=y) in the
# default RPi kernel config, so no kernel-module-* packages are needed.
# This packagegroup exists as a hook for any future initramfs additions
# (e.g., out-of-tree kernel modules or userspace tools needed at early boot).

RDEPENDS:${PN} = ""
