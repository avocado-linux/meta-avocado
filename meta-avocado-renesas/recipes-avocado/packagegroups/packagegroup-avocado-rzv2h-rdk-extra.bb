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
RDEPENDS:${PN} = "kernel-modules"

# TODO(after first boot): mirror packagegroup-avocado-solidrun-extra and add the
# RZ/V2H multimedia (mmngr/vspm), Wayland/display, DRP-AI3 userspace
# (from renesas-rz/rzv2h_drp-ai_driver), and board firmware groups once the
# exact recipe/package names are confirmed against a build. Kept minimal here so
# the feed wiring exists without RDEPENDing on recipes that are not yet proven
# to build for this machine.
