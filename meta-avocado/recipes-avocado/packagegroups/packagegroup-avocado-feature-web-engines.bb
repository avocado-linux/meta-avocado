DESCRIPTION = "Packagegroup for the Avocado web-engines feature group: chromium and qtwebengine"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

# The two web engines are kept out of kas/feature/almost-complete.yml because
# each is a whole-browser compile that outlasts the rest of an umbrella build.
# Stack kas/feature/web-engines.yml to build them. The gates match the groups they
# came from: chromium needs opengl and wayland (browsers), qtwebengine needs
# opengl (qt).

# A machine family can drop chromium it cannot build, as the browsers group
# allows: qcom-base.inc sets BROWSER_PACKAGES:qcom = "" (chromium 146 needs
# wayland >= 1.24). The default is the browsers group's.
BROWSER_PACKAGES ?= "${@bb.utils.contains('DISTRO_FEATURES', 'opengl wayland', 'chromium-ozone-wayland', '', d)}"

RDEPENDS:${PN} = " \
  ${BROWSER_PACKAGES} \
  ${@bb.utils.contains('DISTRO_FEATURES', 'opengl', 'qtwebengine', '', d)} \
"
