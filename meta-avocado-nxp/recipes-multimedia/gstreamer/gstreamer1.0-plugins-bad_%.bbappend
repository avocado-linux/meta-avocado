# See gstreamer1.0_%.bbappend in this dir for rationale. meta-imx already
# scopes this one to MACHINE_SOCARCH on mx8/imxpxp via old _<override> syntax;
# this restates it unconditionally under new : syntax so it always sticks.
PACKAGE_ARCH = "${MACHINE_SOCARCH}"
