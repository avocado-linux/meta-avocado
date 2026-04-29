# Depend on tegraflash-bsp, tools, and related images for provisioning
do_compile[depends] += "tegraflash-bsp:do_deploy"
do_compile[depends] += "tegraflash-tools-deploy:do_deploy"
do_compile[depends] += "tegra-espimage:do_image_complete"
do_compile[depends] += "tos-optee:do_deploy"

SRC_URI += " \
  file://stone-provision-tegraflash.sh \
  file://stone-provision-noop.sh \
"

DEPENDS += " jq-native"
# Use tegraflash profile to validate all required files are present during build
AVOCADO_PROVISION_PROFILE = "tegraflash"

# Only run validation for nvidia targets (not create or provision)
STONE_BUILD_TASK = "do_stone_validate"

do_deploy:append() {
  install -d ${DEPLOYDIR}
  install -m 0755 ${UNPACKDIR}/stone-provision-tegraflash.sh ${DEPLOYDIR}/stone-provision-tegraflash.sh
  install -m 0755 ${UNPACKDIR}/stone-provision-noop.sh ${DEPLOYDIR}/stone-provision-noop.sh
}
