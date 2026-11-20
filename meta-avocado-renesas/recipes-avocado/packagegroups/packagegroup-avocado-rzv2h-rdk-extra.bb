DESCRIPTION = "Packagegroup for Renesas RZ/V2H Robot RDK extra packages"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

# kernel-modules publishes every built module as an individual
# kernel-module-<name> package in the feed, which the avocado-bsp-rzv2h-rdk
# extension's `kernel-modules: '*'` request resolves against. This is the
# load-bearing entry (see docs/adding-a-machine-target.md section 9); without it
# `avocado ext install` for the board cannot resolve its modules.
# MACHINE_EXTRA_RRECOMMENDS carries the board's debug/probe toolset from
# avocado-rzv2h-rdk.conf. Expanding it here is what makes it reachable: nothing
# else in an avocado build reads it, since packagegroup-base is an oe-core
# packagegroup this distro does not install (packagegroup-avocado-rootfs.bb
# documents dropping core-boot). meta-avocado-qcom, -raspberrypi and -rockchip
# wire it the same way.
RDEPENDS:${PN} = " \
    kernel-modules \
    ${MACHINE_EXTRA_RRECOMMENDS} \
"

# TODO(after first boot): mirror packagegroup-avocado-solidrun-extra and add the
# RZ/V2H multimedia (mmngr/vspm), Wayland/display, DRP-AI3 userspace
# (from renesas-rz/rzv2h_drp-ai_driver), and board firmware groups once the
# exact recipe/package names are confirmed against a build. Kept minimal here so
# the feed wiring exists without RDEPENDing on recipes that are not yet proven
# to build for this machine.
