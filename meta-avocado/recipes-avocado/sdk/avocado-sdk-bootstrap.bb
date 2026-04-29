SUMMARY = "Avocado SDK bootstrap"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

PV = "${SDK_VERSION}"

PACKAGE_ARCH = "${SDKPKGARCH}"
PACKAGES = "${PN}"
inherit packagegroup nospdx

# Wrynose tightened the build-deps QA check to fatal. This recipe is a
# metadata-only aggregator (RDEPENDS-only) — its rdeps are intentionally
# not build-time deps. Same pattern as avocado-sdk-toolchain.bb and
# avocado-sdk-target.bb in this tree.
INSANE_SKIP:${PN} += "build-deps"

RDEPENDS:${PN} += " \
  avocado-sdk-environment \
  nativesdk-dnf \
  nativesdk-bash \
  nativesdk-opkg \
  nativesdk-ca-certificates \
  nativesdk-curl \
  nativesdk-git \
"
