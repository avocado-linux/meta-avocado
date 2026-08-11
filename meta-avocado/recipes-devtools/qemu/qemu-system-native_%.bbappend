# qemu-system-native's configure auto-detects the build host's libkeyutils
# and enables the cryptodev-lkcf backend. The backend is not covered by a
# DEPENDS, so a hermetic rebuild whose recipe sysroot lacks keyutils.h fails
# compiling backends/cryptodev-lkcf.c. Pull keyutils-native into the sysroot
# so the backend builds from a staged header rather than a host one, keeping
# the result reproducible across build machines.
DEPENDS += "keyutils-native"
