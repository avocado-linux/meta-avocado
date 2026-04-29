DESCRIPTION = "Packagegroup for Avocado SDK All Metadata packages"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "all_avocadosdk"
# Metadata-only packagegroup with no upstream source — wrynose's
# create-spdx requires a static SPDX document for such recipes
# ("Could not find a static SPDX document named static-..."). We have
# nothing to SBOM here, so opt this recipe out and keep the SBOM
# pipeline intact for real packages.
inherit packagegroup nospdx
PACKAGES = "${PN}"

RDEPENDS:${PN} = " \
  ${VIRTUAL-RUNTIME_avocado-sdk-metadata} \
"
