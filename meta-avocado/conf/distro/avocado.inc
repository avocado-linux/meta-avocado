DISTRO = "avocado"
DISTRO_NAME = "Avocado OS"

SDK_VENDOR = "-avocadosdk"
SDK_VERSION := "${@'${DISTRO_VERSION}'.replace('snapshot-${METADATA_REVISION}','snapshot')}"
SDK_VERSION[vardepvalue] = "${SDK_VERSION}"
TCLIBCAPPEND = ""

MAINTAINER = "Avocado Developers <info@avocadolinux.org>"

TARGET_VENDOR = "-avocado"

REQUIRED_AVOCADO_BBLAYERS_CONF_VERSION = "${DISTRO}-1"

LOCALCONF_VERSION = "2"

# We don't actually package the yocto SDK, but declare these anyways
SDK_NAME = "${DISTRO}-${TCLIBC}-${SDKMACHINE}-${IMAGE_BASENAME}-${TUNE_PKGARCH}-${MACHINE}"
SDKPATHINSTALL = "/opt/${DISTRO}/${SDK_VERSION}"

# Configure the base sysroot directory for SDK packages.
#   Packaging breaks if this is configured to "/", or ""
#   Even though it would be preferrable considering we control the sysroot of installation
SDKPATHNATIVE = "/opt/_avocado/sdk"
SDKPATH = "${SDKPATHNATIVE}"

SDK_VENDOR = "-avocadosdk"
SDKPKGSUFFIX = "avocadosdk"
SDKPKGARCH = "${SDKMACHINE}-${SDKPKGSUFFIX}"

PACKAGE_CLASSES ?= "package_rpm"

SANITY_TESTED_DISTROS ?= " \
            ubuntu-22.04 \n \
            ubuntu-24.04 \n \
            fedora-40 \n \
            "

require conf/distro/include/no-static-libs.inc
require conf/distro/include/yocto-uninative.inc
require conf/distro/include/security_flags.inc
INHERIT += "uninative"

BB_SIGNATURE_HANDLER ?= "OEEquivHash"
BB_HASHSERVE ??= "auto"

MACHINE_SHORT_NAME = "${@d.getVar('MACHINE').replace('avocado-','')}"
VIRTUAL-RUNTIME_avocado-sdk-metadata = "avocado-sdk-${MACHINE_SHORT_NAME}"
VIRTUAL-RUNTIME_dbus ?= "dbus"

ROOTFS_IMAGE_EXTRA_INSTALL ??= ""
INITRAMFS_IMAGE_EXTRA_INSTALL ??= ""
PKG_EXTRA_INSTALL ??= ""
SDK_TOOLCHAIN_EXTRA_INSTALL ??= ""
SDK_PKG_EXTRA_INSTALL ??= ""
