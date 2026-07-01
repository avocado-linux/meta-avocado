FILESEXTRAPATHS:prepend := "${THISDIR}/tegra-helper-scripts:"

# Install the avocado SoC-split flash helpers alongside upstream's generic
# tegra-flash-helper.sh in ${bindir}/tegra-flash. tegraflash-bsp selects the
# per-SoC helper via FLASH_HELPER_SCRIPT (tegra234-flash-helper.sh, and
# tegra264-flash-helper.sh on tegra264/Thor) and writes it into the flash
# .env as FLASH_HELPER; initrd-flash then execs "$here/$FLASH_HELPER" from the
# runtime stone _build/tegraflash dir.
#
# That dir is populated by tegraflash-tools-deploy, which copies the *native*
# ${bindir}/tegra-flash tree. Without installing the split helpers here they
# only ever land in the SDK (nativesdk-tegraflash-tools), so provisioning fails
# with e.g. ".../_build/tegraflash/tegra264-flash-helper.sh: No such file".
# Installing them via this bbappend (recipe is BBCLASSEXTEND native/nativesdk)
# routes them through -native into the runtime deploy, fixing both tegra234
# (Orin) and tegra264 (Thor) provisioning. (S = ${UNPACKDIR}, per upstream.)
SRC_URI += " \
    file://tegra234-flash-helper.sh \
    file://tegra264-flash-helper.sh \
"

do_install:append() {
    install -m 0755 ${S}/tegra234-flash-helper.sh ${D}${bindir}/tegra-flash/tegra234-flash-helper.sh
    install -m 0755 ${S}/tegra264-flash-helper.sh ${D}${bindir}/tegra-flash/tegra264-flash-helper.sh
}
