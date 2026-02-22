DESCRIPTION = "Packagegroup for SolidRun RZ/V2N extra packages"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

RDEPENDS:${PN} = "${MULTIMEDIA_KERNEL_MODULES} \
    ${MULTIMEDIA_USERSPACE_LIBS} \
    ${GSTREAMER_PACKAGES} \
    ${DISPLAY_PACKAGES} \
    ${CAMERA_PACKAGES}"

# Out-of-tree Renesas multimedia kernel modules (display pipeline)
MULTIMEDIA_KERNEL_MODULES = "kernel-module-mmngr \
    kernel-module-mmngrbuf \
    kernel-module-vspm \
    kernel-module-vspmif"

# Renesas multimedia userspace libraries
MULTIMEDIA_USERSPACE_LIBS = "mmngr-user-module \
    mmngrbuf-user-module \
    vspmif-user-module"

# GStreamer multimedia framework
GSTREAMER_PACKAGES = "gstreamer1.0 \
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad \
    gstreamer1.0-plugins-bad-bayer \
    gstreamer1.0-plugins-bad-waylandsink \
    gstreamer1.0-plugins-ugly \
    gstreamer1.0-plugin-vspmfilter \
    gstreamer1.0-rtsp-server"

# Wayland/Weston display stack
DISPLAY_PACKAGES = "weston \
    weston-init \
    libdrm \
    libdrm-tests \
    wayland-utils \
    adwaita-icon-theme \
    xcursor-transparent-theme"

# Camera and V4L2 support
CAMERA_PACKAGES = "v4l-utils \
    media-ctl \
    kernel-module-uvcvideo \
    yavta \
    v4l2-init-scripts"
