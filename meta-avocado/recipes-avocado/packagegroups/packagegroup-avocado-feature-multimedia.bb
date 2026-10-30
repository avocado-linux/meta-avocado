DESCRIPTION = "Packagegroup for the Avocado multimedia feature"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

RDEPENDS:${PN} = " \
  ${GSTREAMER_PACKAGES} \
  ${PIPEWIRE_PACKAGES} \
  opencv \
  libv4l \
  v4l-utils \
"

# The audio server and its session manager. Bluetooth audio needs both: bluez hands an A2DP
# device's profile to a media endpoint, and without a server registering one the device pairs but
# never connects. The Bluetooth, systemd-service and ALSA parts come from the recipe's own
# PACKAGECONFIG defaults (DISTRO_FEATURES bluetooth, systemd and alsa), so no override here.
# The list is explicit because pipewire-spa-plugins-meta and pipewire-modules-meta recommend
# libcamera, libopus, libfreeaptx, libjack and webrtc packages the feed does not build, which fails
# an image install; these are the packages an audio-only Bluetooth setup loads.
PIPEWIRE_PACKAGES = " \
  pipewire \
  pipewire-tools \
  pipewire-spa-plugins-bluez5 \
  pipewire-spa-plugins-codec-bluez5-sbc \
  pipewire-spa-plugins-codec-bluez5-hfp-cvsd \
  pipewire-spa-plugins-codec-bluez5-hfp-msbc \
  pipewire-spa-plugins-alsa \
  pipewire-spa-plugins-audioconvert \
  pipewire-spa-plugins-audiomixer \
  pipewire-spa-plugins-audiotestsrc \
  pipewire-spa-plugins-control \
  pipewire-spa-plugins-dbus \
  pipewire-spa-plugins-support \
  pipewire-spa-plugins-volume \
  pipewire-modules-access \
  pipewire-modules-adapter \
  pipewire-modules-client-device \
  pipewire-modules-client-node \
  pipewire-modules-link-factory \
  pipewire-modules-metadata \
  pipewire-modules-profiler \
  pipewire-modules-protocol-native \
  pipewire-modules-rt \
  pipewire-modules-session-manager \
  pipewire-modules-spa-device \
  pipewire-modules-spa-device-factory \
  pipewire-modules-spa-node \
  pipewire-modules-spa-node-factory \
  wireplumber \
  wireplumber-modules-meta \
  wireplumber-scripts \
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
