DISTRO = "avocado"
DISTRO_NAME = "Avocado OS"
DISTRO_VENDOR = "Avocado Linux"
DISTRO_VENDOR_URL = "https://avocadolinux.org"
DISTRO_DOCUMENTATION_URL = "https://docs.avocadolinux.org"

SDK_VENDOR = "-avocadosdk"
SDK_VERSION := "${@'${DISTRO_VERSION}'.replace('snapshot-${METADATA_REVISION}','snapshot')}"
SDK_VERSION[vardepvalue] = "${SDK_VERSION}"

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

# DISABLED 2026-05-31: the inline per-RPM upload (hooking do_package_write_rpm)
# is a Pulp task storm at full-distro scale (1 task + 2 RBAC roles per RPM x ~30k)
# -> DB bloat -> RDS CPU saturation -> api timeouts. Replaced by end-of-build feed
# generation (package-index) + Pulp sync (bulk, native dedup, O(1) tasks). The
# bbclass is kept as reference but no longer globally inherited. See
# infra/project_cloud_pulp_per_rpm_task_storm + pipeline-organization.md.
AVOCADO_PULP_UPLOAD ??= "0"
# INHERIT += "avocado-pulp-upload"   # superseded by package-index + Pulp sync
BB_BASEHASH_IGNORE_VARS:append = " AVOCADO_PULP_UPLOAD AVOCADO_PULP_UPLOAD_EXCLUDE PULP_BASE_URL PULP_USERNAME PULP_PASSWORD"

BB_SIGNATURE_HANDLER ?= "OEEquivHash"
BB_HASHSERVE ??= "${@os.getenv('BB_HASHSERVE') or 'auto'}"

# Keep the hash equivalency database alongside the shared SSTATE_DIR so
# every machine build sees the same equivalence records and can hit each
# other's sstate. Without this, each build dir has its own DB and the
# shared sstate cache is mostly wasted.
BB_HASHSERVE_DB_DIR ??= "${SSTATE_DIR}"

VIRTUAL-RUNTIME_avocado-sdk-metadata = "avocado-sdk-${MACHINE_SHORT_NAME}"
VIRTUAL-RUNTIME_dbus ?= "dbus"

ROOTFS_IMAGE_EXTRA_INSTALL ??= ""
INITRAMFS_IMAGE_EXTRA_INSTALL ??= ""
PKG_EXTRA_INSTALL ??= ""
SDK_TOOLCHAIN_EXTRA_INSTALL ??= ""
SDK_PKG_EXTRA_INSTALL ??= ""
