DESCRIPTION = "Packagegroup for SolidRun RZ/V2N extra packages"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

RDEPENDS:${PN} = "${MULTIMEDIA_KERNEL_MODULES} \
    ${MULTIMEDIA_USERSPACE_LIBS} \
    ${GSTREAMER_PACKAGES} \
    ${DISPLAY_PACKAGES} \
    ${CAMERA_PACKAGES} \
    ${DRPAI_PACKAGES} \
    ${FIRMWARE_PACKAGES}"

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
    xcursor-transparent-theme \
    mesa \
    mesa-megadriver \
    mesa-demos \
    kmscube \
    glmark2"

# Camera and V4L2 support
CAMERA_PACKAGES = "v4l-utils \
    media-ctl \
    kernel-module-uvcvideo \
    yavta \
    v4l2-init-scripts"

# DRP-AI3 inference accelerator (RZ/V2N).
# From renesas-rz/rzv2n_drp-ai_driver's meta-rz-drpai layer (added in
# distro/kas/vendor/renesas.yml). The kernel driver is built into the
# linux-renesas image via recipes-kernel/linux/linux-renesas_6.1.bbappend
# patches; these recipes provide the userspace pieces:
#   - drpai     : UAPI header (linux/drpai.h) for /dev/drpai0
#   - lib-tvm   : prebuilt libtvm_runtime.so.2.5.1 (Apache TVM runtime)
# The full Mera2/DRP/ACL inference stack (libdrp_rt, libmera2_*, libacl_rt)
# is not packaged here — it lives in renesas-rz/rzv_drp-ai_tvm (RUHMI) and
# needs a separate recipe or per-reference bundling.
DRPAI_PACKAGES = "drpai \
    lib-tvm"

# SolidRun board firmware. The Renesas-style MACHINE_ESSENTIAL_EXTRA_RDEPENDS
# in meta-rzv2n/conf/machine/rzv2n-sr-som.conf is a no-op in avocado-os's
# image build (we don't use core-image.bbclass), so the firmware recipe
# would never get pulled into the rootfs / package feed without an
# explicit reference here. Listing the cyw43455 sub-package forces the
# linux-firmware-sr-rz_git.bb recipe to build, which makes all of its
# sub-packages available so the avocado-bsp-rzv2n-sr-som extension's
# `linux-firmware-sr-rz-cyw43455: '*'` request resolves.
FIRMWARE_PACKAGES = "linux-firmware-sr-rz-cyw43455"
