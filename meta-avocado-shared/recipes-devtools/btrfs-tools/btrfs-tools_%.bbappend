# Avocado-side override on top of upstream OE-core's btrfs-tools recipe.
# Adds an avocado-specific patch only for the native variant: a fakeroot
# uid/gid stat fix needed for our build environment.
#
# Wrynose: dropped the local backport `btrfs-tools_6.14.bb` (OE-core
# wrynose ships 6.19.1) and the upstream-mirror python-modules-path
# patch. Keeping this bbappend + the one truly avocado patch.

FILESEXTRAPATHS:prepend := "${THISDIR}/btrfs-tools:"

SRC_URI:append:class-native = " file://0001-Fix-uid-gid-stat-for-fakeroot.patch"
