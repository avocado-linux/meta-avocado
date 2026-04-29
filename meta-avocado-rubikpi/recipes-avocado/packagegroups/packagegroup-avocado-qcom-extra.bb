DESCRIPTION = "Packagegroup for extra qcom features"

LICENSE = "BSD-3-Clause-Clear"

PACKAGE_ARCH = "${TUNE_PKGARCH}"
inherit packagegroup nospdx
PROVIDES = "${PACKAGES}"
PACKAGES = "${PN}"

RDEPENDS:${PN} = "gstreamer1.0 \
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad \
    gstreamer1.0-rtsp-server \
    packagegroup-qcom-display \
    packagegroup-qcom-graphics \
    packagegroup-qcom-video \
    v4l-utils"
