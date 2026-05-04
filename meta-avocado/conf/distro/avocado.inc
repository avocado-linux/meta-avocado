DISTRO = "avocado"
DISTRO_NAME = "Avocado OS"
DISTRO_VENDOR = "Avocado Linux"
DISTRO_VENDOR_URL = "https://avocadolinux.org"
DISTRO_DOCUMENTATION_URL = "https://docs.avocadolinux.org"

SDK_VENDOR = "-avocadosdk"
SDK_VERSION := "${@'${DISTRO_VERSION}'.replace('snapshot-${METADATA_REVISION}','snapshot')}"
SDK_VERSION[vardepvalue] = "${SDK_VERSION}"
TCLIBCAPPEND = ""

MAINTAINER = "Avocado Developers <info@avocadolinux.org>"
HOMEPAGE = "${DISTRO_VENDOR_URL}"
TARGET_VENDOR = "-avocado"

REQUIRED_AVOCADO_BBLAYERS_CONF_VERSION = "${DISTRO}-1"

LOCALCONF_VERSION = "2"

MACHINE_SHORT_NAME = "${@d.getVar('MACHINE').replace('avocado-','')}"

# We don't actually package the yocto SDK, but declare these anyways
SDK_NAME = "${DISTRO}-${TCLIBC}-${SDKMACHINE}-${IMAGE_BASENAME}-${TUNE_PKGARCH}-${MACHINE}"
SDKPATHINSTALL = "/opt/${DISTRO}/${SDK_VERSION}"

# Configure the base sysroot directory for SDK packages.
#   Packaging breaks if this is configured to "/", or ""
#   Even though it would be preferrable considering we control the sysroot of installation
SDKPATH = "/opt/_avocado/${MACHINE_SHORT_NAME}/sdk"
SDKPATHNATIVE = "${SDKPATH}/${SDK_ARCH}"

SDK_VENDOR = "-avocadosdk"
SDKPKGSUFFIX = "avocadosdk"
SDKPKGARCH = "${SDK_ARCH}-${SDKPKGSUFFIX}"
SDKIMGARCH = "${MACHINE_SHORT_NAME}-${SDKPKGSUFFIX}"

PACKAGE_CLASSES ?= "package_rpm"

# SPDX SBOM configuration
# create-spdx is inherited by default via OE-Core INHERIT_DISTRO.
# These variables customize the metadata in generated SPDX documents.
SPDX_ORG = "${DISTRO_VENDOR}"
SPDX_SUPPLIER = "Organization: ${DISTRO_VENDOR}"
SPDX_PRETTY = "1"

SANITY_TESTED_DISTROS ?= " \
            ubuntu-22.04 \n \
            ubuntu-24.04 \n \
            fedora-40 \n \
            "

require conf/distro/include/no-static-libs.inc
require conf/distro/include/yocto-uninative.inc
require conf/distro/include/security_flags.inc
INHERIT += "uninative"

# Always inherit avocado-pulp-upload so per-recipe manifests are written even
# in dev builds. The bbclass body gates Pulp HTTP traffic on
# AVOCADO_PULP_UPLOAD=1 (set by kas/ci/pulp-upload.yml in CI); other builds
# get dry-run manifest entries that distro/scripts/check-pulp-parity.sh can
# audit locally. The Pulp env vars are excluded from basehashes so toggling
# upload mode and rotating creds do not invalidate sstate.
AVOCADO_PULP_UPLOAD ??= "0"
INHERIT += "avocado-pulp-upload"
BB_BASEHASH_IGNORE_VARS:append = " AVOCADO_PULP_UPLOAD AVOCADO_PULP_UPLOAD_EXCLUDE PULP_BASE_URL PULP_USERNAME PULP_PASSWORD"

BB_SIGNATURE_HANDLER ?= "OEEquivHash"
BB_HASHSERVE ??= "${@os.getenv('BB_HASHSERVE') or 'auto'}"

VIRTUAL-RUNTIME_avocado-sdk-metadata = "avocado-sdk-${MACHINE_SHORT_NAME}"
VIRTUAL-RUNTIME_dbus ?= "dbus"

ROOTFS_IMAGE_EXTRA_INSTALL ??= ""
INITRAMFS_IMAGE_EXTRA_INSTALL ??= ""
PKG_EXTRA_INSTALL ??= ""
SDK_TOOLCHAIN_EXTRA_INSTALL ??= ""
SDK_PKG_EXTRA_INSTALL ??= ""
