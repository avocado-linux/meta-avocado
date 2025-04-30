DESCRIPTION = "Avocado SDK toolchain"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

# Specify that this is for the SDK host/SDKMACHINE
INHIBIT_DEFAULT_DEPS = "1"
PACKAGE_ARCH = "${SDKPKGARCH}"
PACKAGES = "${PN}"

TARGET_ARCH = "${SDK_ARCH}"

# These variables are derived from meta-avocado/classes/populate_sdk_base.bbclass
TOOLCHAIN_HOST_TASK = " \
    nativesdk-packagegroup-sdk-host \
    packagegroup-cross-canadian-${MACHINE} \
    ${@bb.utils.contains('SDK_TOOLCHAIN_LANGS', 'go', 'packagegroup-go-cross-canadian-${MACHINE}', '', d)} \
    ${@bb.utils.contains('SDK_TOOLCHAIN_LANGS', 'rust', 'packagegroup-rust-cross-canadian-${MACHINE}', '', d)} \
"

TOOLCHAIN_TARGET_TASK = " \
    ${@multilib_pkg_extend(d, 'packagegroup-core-standalone-sdk-target')} \
    ${@bb.utils.contains('SDK_TOOLCHAIN_LANGS', 'go', multilib_pkg_extend(d, 'packagegroup-go-sdk-target'), '', d)} \
    ${@bb.utils.contains('SDK_TOOLCHAIN_LANGS', 'rust', multilib_pkg_extend(d, 'libstd-rs'), '', d)} \
"

# Define package dependencies based on toolchain components
DEPENDS += "${TOOLCHAIN_TARGET_TASK}"
RDEPENDS:${PN} = "${TOOLCHAIN_HOST_TASK} meta-environment-${MACHINE}"

# Skip the build-deps QA check as it gives false positives for SDK toolchain recipes
# where RDEPENDS are dynamically generated.
INSANE_SKIP:${PN} += " build-deps"

# Allow additional languages to be specified
SDK_TOOLCHAIN_LANGS ?= ""
SDK_TOOLCHAIN_LANGS:remove:sdkmingw32 = "rust"
SDK_TOOLCHAIN_LANGS:remove:mipsarchn32 = "rust"

# Make sure our package doesn't contain any files
FILES:${PN} = "${datadir}/${PN}/*"

# Add the runtime package name mapping from populate_sdk_base.bbclass
python package:prepend() {
    import oe.packagedata

    pn = d.getVar('PN')
    bb.warn("pn: %s" % pn)

    # Resolve TOOLCHAIN_TARGET_TASK package names
    oe.packagedata.runtime_mapping_rename("TOOLCHAIN_TARGET_TASK", pn, d)

    # Create a copy of data for the host packages
    ld = bb.data.createCopy(d)
    ld.setVar("PKGDATA_DIR", "${STAGING_DIR}/${SDK_ARCH}-${SDKPKGSUFFIX}${SDK_VENDOR}-${SDK_OS}/pkgdata")
    oe.packagedata.runtime_mapping_rename("TOOLCHAIN_HOST_TASK", pn, ld)
    d.setVar("TOOLCHAIN_HOST_TASK", ld.getVar("TOOLCHAIN_HOST_TASK"))

    # Update the package dependencies
    d.setVar("RDEPENDS:${PN}", "${TOOLCHAIN_TARGET_TASK} ${TOOLCHAIN_HOST_TASK}")
}

# Make sure we have the necessary dependencies
do_package[depends] += "virtual/libc:do_packagedata"

# Ensure this is considered an SDK recipe
inherit nativesdk

SDK_VERSION = "${DISTRO_VERSION}"
PV = "${SDK_VERSION}"

# Skip unneeded tasks
do_configure[noexec] = "1"
do_compile[noexec] = "1"

do_install() {
    install -d ${D}${datadir}/${PN}
    echo "Avocado SDK Toolchain ${PV}" > ${D}${datadir}/${PN}/README
    echo "${PV}" > ${D}${datadir}/${PN}/version
}

# Only package the README and version file
FILES:${PN} = "${datadir}/${PN}/*"
