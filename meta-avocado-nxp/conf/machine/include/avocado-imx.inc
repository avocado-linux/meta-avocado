MACHINEOVERRIDES =. "avocado-imx:"

# The i.MX boot chain under its own recipe names - AVOCADO_CVE_BOOT_CHAIN's
# default names u-boot and trusted-firmware-a, neither of which this board
# builds. Appended rather than set, so the default's optee-os survives.
# imx-atf and u-boot-imx emit -dbg/-dev packages, so without this they scope
# feed: real bootloader CVEs filed as "not in this image".
AVOCADO_CVE_BOOT_CHAIN:append = " imx-atf imx-boot u-boot-imx imx-system-manager \
                                  imx-oei firmware-imx imx-boot-firmware-files \
                                  firmware-ele-imx"

# The opaque half of that list: NXP binaries unpacked from a vendor tarball,
# with no upstream source and no CPE that any spelling of the name matches, so
# cve-check scans them under BPN and writes a zero indistinguishable from a
# clean scan. Declared here so avocado-cve-optout leaves a marker and they land
# in unscanned_recipes rather than no_cve_record_recipes. imx-boot is the
# container imx-mkimage assembles; u-boot-imx and imx-atf inside it are scanned
# on their own recipes, so scanning it too would only double-count them.
CVE_CHECK_SKIP_RECIPE:append = " imx-boot imx-boot-firmware-files \
                                 imx-system-manager imx-oei firmware-imx \
                                 firmware-ele-imx"
