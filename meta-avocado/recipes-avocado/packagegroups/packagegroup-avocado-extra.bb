DESCRIPTION = "Packagegroup for Avocado extra"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
# Metadata-only packagegroup with no upstream source - wrynose's create-spdx
# requires a static SPDX document for such recipes ("Could not find a static
# SPDX document named static-..."). Nothing to SBOM here, so opt out and keep
# the SBOM pipeline intact for real packages.
inherit packagegroup nospdx
PACKAGES = "${PN}"

# SDK target sysroot - target-arch (MACHINE_ARCH) build deps for compiling extensions
# against the target. Moved here from packagegroup-avocado-sdk-extra: the distro build
# builds target-arch (-> target feed), the SDK build builds host/nativesdk (-> sdk feed).
# avocado-sdk-target-sysroot lands in the target feed where the CLI's combined repo conf
# installs it. This is a feed-only packagegroup (via avocado-pkg-extra), so these dev
# packages are installable from the feed but not baked into the rootfs.
SDK_SYSROOT_DEPENDS = " \
  avocado-sdk-target-sysroot \
  kernel-devsrc \
  ${@multilib_pkg_extend(d, 'libstd-rs')} \
  ${@multilib_pkg_extend(d, 'packagegroup-go-sdk-target')} \
"

RDEPENDS:${PN} = " \
  ${SDK_SYSROOT_DEPENDS} \
  avocado-hitl \
  avocado-img-bootfiles \
  avocado-img-initramfs \
  avocado-img-rootfs \
  avocado-img-var \
  avocado-pkg-rootfs \
  avocado-pkg-initramfs \
  linux-firmware \
  phytool \
  qemu-user-static \
  qemu-user-static-binfmt \
  qemu-guest-agent \
"

RDEPENDS:${PN} += "${@' '.join('packagegroup-avocado-feature-' + g for g in (d.getVar('AVOCADO_FEATURE_GROUPS') or '').split())}"
