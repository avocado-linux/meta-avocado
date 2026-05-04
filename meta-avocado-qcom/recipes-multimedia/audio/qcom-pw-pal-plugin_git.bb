# Override of meta-qcom-hwe's qcom-pw-pal-plugin_git.bb. Higher BBFILE_PRIORITY
# in our layer (9) wins over upstream (6).
#
# Why we override: the rubikpi3 needs an HDMI-as-default-audio-sink config
# (see 0001-modify-pipewire-configuration-for-rubikpi3.patch). That patch
# targets the older monolithic `pulseaudio-plugin` repo (which contains both
# pipewire-plugin/ and modules/pa-pal-plugins/ as subdirs). Upstream
# meta-qcom-hwe split into the smaller `pipewire-plugin` repo and the patch
# no longer applies cleanly. Pin to the layout the patch was authored against.
#
# Source: https://github.com/rubikpi-ai/meta-rubikpi-bsp @ 227631ce94bb
inherit autotools pkgconfig

SUMMARY = "Pipewire PAL plugin (rubikpi3-tuned: HDMI-default audio routing)"
LICENSE = "BSD-3-Clause-Clear"
LIC_FILES_CHKSUM = "file://${QCOM_COMMON_LICENSE_DIR}${LICENSE};md5=3771d4920bd6cdb8cbdf1e8344489ee0"

SRCPROJECT = "git://git.codelinaro.org/clo/le/platform/vendor/qcom-opensource/pulseaudio-plugin.git;protocol=https"
SRCBRANCH  = "audio-algos.lnx.1.0.r1-rel"
SRCREV     = "35adad85a280ea8dc72f5687c1a70ddc9833758c"

SRC_URI = "${SRCPROJECT};branch=${SRCBRANCH};destsuffix=audio/opensource/pulseaudio-plugins"
SRC_URI += " \
    file://pipewire-pulse.service \
    file://pipewire-pulse.socket \
    file://98-qcom-pipewire.preset \
    file://0001-modify-pipewire-configuration-for-rubikpi3.patch;patchdir=${RUBIKPI3_S} \
"

S = "${WORKDIR}/audio/opensource/pulseaudio-plugins/pipewire-plugin"
RUBIKPI3_S = "${WORKDIR}/audio/opensource/pulseaudio-plugins"

DEPENDS = "qcom-agm pipewire qcom-pal qcom-pal-headers"
TARGET_CFLAGS += "-I ${STAGING_DIR_TARGET}/usr/include/spa-0.2"
TARGET_CFLAGS += "-I ${STAGING_DIR_TARGET}/usr/include/pipewire-0.3"

SYSTEMD_PACKAGES += "${PN} ${PN}-systemd"
SYSTEMD_SERVICE:${PN} += "pipewire-pulse.socket"
SYSTEMD_SERVICE:${PN} += "98-qcom-pipewire.preset"
SYSTEMD_SERVICE:${PN} += " pipewire-pulse.service"
SYSTEMD_AUTO_ENABLE:${PN} = "enable"
SYSTEMD_AUTO_ENABLE:${PN}-systemd = "enable"

do_install:append:qcom () {
    install -d ${D}${systemd_system_unitdir}
    install -d ${D}${nonarch_libdir}/systemd/system-preset
    install -d ${D}/usr/lib/pipewire-0.3
    install -m 0644 ${WORKDIR}/pipewire-pulse.service ${D}${systemd_system_unitdir}/pipewire-pulse.service
    install -Dm0644 ${WORKDIR}/98-qcom-pipewire.preset ${D}${nonarch_libdir}/systemd/system-preset/98-qcom-pipewire.preset
    install -Dm0644 ${WORKDIR}/pipewire-pulse.socket ${D}${systemd_system_unitdir}/pipewire-pulse.socket
    install -d ${D}${systemd_system_unitdir}/multi-user.target.wants/
    install -m 0755  ${D}/usr/lib/libpipewire-module-pal.so ${D}/usr/lib/pipewire-0.3/
    rm -f ${D}/usr/lib/libpipewire-module-pal.so
}

SOLIBS = ".so*"
FILES_SOLIBSDEV = ""

FILES:${PN} += "${libdir}/*.so ${libdir}/pkgconfig/ ${systemd_unitdir}/system/* ${sysconfdir}/* ${bindir}/* /usr/lib/pipewire-0.3 /usr/lib/systemd/system-preset /usr/share/wireplumber/wireplumber.conf.d /usr/share/pipewire/pipewire.conf.d"
FILES:${PN} += "${systemd_system_unitdir}/pipewire-pulse.service"
FILES:${PN} += "${systemd_system_unitdir}/pipewire-pulse.socket"
FILES_${PN} += "/usr/lib/systemd/system-preset/98-qcom-pipewire.preset"
FILES_${PN} += "/usr/share/wireplumber/wireplumber.conf.d/60-disable-alsa.conf"
FILES_${PN} += "/usr/share/pipewire/pipewire.conf.d/pw-pal-plugin.conf"
FILES:${PN}-dev = "${libdir}/*.la ${includedir}"
INSANE_SKIP:${PN} = "dev-so"
