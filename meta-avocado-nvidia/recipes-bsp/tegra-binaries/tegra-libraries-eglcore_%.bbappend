# SPDX-License-Identifier: MIT
#
# Ship the tegra-egl/libEGL_nvidia.so.0 link in the package instead of creating
# it in a postinstall.
#
# meta-tegra's tegra-libraries-eglcore creates
# /usr/lib/aarch64-linux-gnu/tegra-egl/libEGL_nvidia.so.0 in pkg_postinst, using
# $D-prefixed paths. That works when the OE rootfs build runs the script with D
# set, but avocado installs the package with dnf into an install root and the
# scriptlet then runs with D empty, so `install -d` and `ln -f` act on the SDK
# container's own filesystem. The ln fails ("failed to access
# '/usr/lib/libEGL_nvidia.so.0'", rpm warns the %post scriptlet failed) and the
# link is never created in the sysroot, so the libraries that hard-code this
# path (argus, scf) cannot find the EGL library.
#
# The same hard link is made in do_install, so it is part of the file list and
# any installer creates it. The postinstall becomes a no-op so it does not run
# against the wrong root and dnf installs stop warning.
do_install:append() {
    install -d ${D}${libdir}/aarch64-linux-gnu/tegra-egl
    ln -f ${D}${libdir}/libEGL_nvidia.so.0 ${D}${libdir}/aarch64-linux-gnu/tegra-egl/
}

pkg_postinst:${PN}() {
    :
}

FILES:${PN} += "${libdir}/aarch64-linux-gnu/tegra-egl"
