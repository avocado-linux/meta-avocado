# Device classes customers plug into a board (USB serial, CAN, container
# networking, input, USB audio, Bluetooth, USB Ethernet), built as modules.
#
# `require` this from a vendor kernel bbappend. The layer builds the universe;
# a runtime composes what it needs from the kernel-module-* packages through
# extensions, so a module costs nothing on a device that doesn't install it.
#
# device-classes.cfg only adds =m (and two booleans). It never lists an option
# as =m that a kernel builds in, but it can't know every vendor defconfig:
# before requiring it from a new kernel, configure once and confirm no option
# went from =y to =m (compare .config before and after; the count must be 0).
FILESEXTRAPATHS:prepend := "${AVOCADO_KERNEL_CFG_DIR}:"
SRC_URI += " file://device-classes.cfg"
