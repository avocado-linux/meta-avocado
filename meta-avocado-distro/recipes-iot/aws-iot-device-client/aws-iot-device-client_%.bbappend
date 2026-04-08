FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

# The meta-aws ExternalProject patch for the bundled SDK removes the empty
# CONFIGURE/BUILD/INSTALL/TEST commands, causing a cross-compilation failure
# (cmake ABI detection without OE's toolchain file). This patch restores them
# so ExternalProject only locates the pre-fetched source without building it.
SRC_URI:append = " file://002-fix-external-project-sdk-no-configure.patch"

# OE's git fetcher checks out SRCREV without tag refs, so git describe (used by
# CMakeLists.txt.versioning) fails. Create a tag before cmake runs.
# Use git -C to avoid changing cwd away from ${B} (cmake needs to run there).
do_configure:prepend() {
    git -C ${S} tag -f "v${PV}" HEAD
}
