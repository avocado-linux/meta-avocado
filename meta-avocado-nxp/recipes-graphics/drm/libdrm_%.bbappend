# meta-imx's libdrm fork scopes to MACHINE_SOCARCH via old _<override> syntax;
# restate unconditionally under new : syntax so it always sticks and the
# .imx-versioned RPM never lands in the shared TUNE_PKGARCH feed.
PACKAGE_ARCH = "${MACHINE_SOCARCH}"
