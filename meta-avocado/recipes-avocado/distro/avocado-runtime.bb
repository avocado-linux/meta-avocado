SUMMARY = "Avocado OS meta package"
DESCRIPTION = "Meta package for Avocado OS distribution components"
LICENSE = "MIT"

# Version set to distro version
PV = "${DISTRO_VERSION}"

# Machine-specific architecture
PACKAGE_ARCH = "${MACHINE_ARCH}"

# Only build the main package, no dev/test/etc variants
PACKAGES = "${PN}"

# Runtime dependencies
RDEPENDS:${PN} = "\
    avocado-img-rootfs \
    avocado-img-initramfs \
    avocado-img-bootfiles \
"

# Meta packages are empty (no files)
ALLOW_EMPTY:${PN} = "1"

