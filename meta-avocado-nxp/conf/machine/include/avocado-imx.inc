MACHINEOVERRIDES =. "avocado-imx:"

# The i.MX boot chain under its own recipe names - AVOCADO_CVE_BOOT_CHAIN's
# default names u-boot and trusted-firmware-a, neither of which this board
# builds. Appended rather than set, so the default's optee-os survives.
# imx-atf and u-boot-imx emit -dbg/-dev packages, so without this they scope
# feed: real bootloader CVEs filed as "not in this image".
AVOCADO_CVE_BOOT_CHAIN:append = " imx-atf imx-boot u-boot-imx imx-system-manager \
                                  imx-oei firmware-imx imx-boot-firmware-files"
