DESCRIPTION = "Packagegroup for the Avocado multimedia feature"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

RDEPENDS:${PN} = " \
  ${GSTREAMER_PACKAGES} \
  opencv \
  libv4l \
  v4l-utils \
"

GSTREAMER_PACKAGES = " \
  gstreamer1.0 \
  gstreamer1.0-plugins-base \
  gstreamer1.0-plugins-good \
  gstreamer1.0-plugins-bad \
  gstreamer1.0-plugins-ugly \
  gstreamer1.0-libav \
"

# mpeg2dec is deliberately absent. No layer in this configuration provides
# it — it has never existed in the vendored meta-openembedded fork, at the
# pinned commit or anywhere in its history — so listing it made the whole
# packagegroup unbuildable:
#
#   Nothing RPROVIDES 'mpeg2dec' (but packagegroup-avocado-feature-multimedia
#   RDEPENDS on or otherwise requires it)
#
# which takes avocado-extra and avocado-complete down with it. The only
# other reference is PACKAGECONFIG[mpeg2dec] on gstreamer1.0-plugins-ugly,
# an option that needs the same missing recipe, so it cannot be enabled
# either. The 2024 feed carries mpeg2dec RPMs, which is where the
# expectation came from; those were produced by an older layer set.
