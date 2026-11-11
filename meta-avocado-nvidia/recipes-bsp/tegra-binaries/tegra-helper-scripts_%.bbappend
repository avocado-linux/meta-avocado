FILESEXTRAPATHS:prepend := "${THISDIR}/tegra-helper-scripts:"

# Install the avocado tegra234 flash helper alongside upstream's generic
# tegra-flash-helper.sh in ${bindir}/tegra-flash. tegraflash-bsp selects the
# helper via FLASH_HELPER_SCRIPT (tegra234-flash-helper.sh on Orin; upstream's
# tegra-flash-helper.sh on tegra264/Thor) and writes it into the flash .env as
# FLASH_HELPER; initrd-flash then execs "$here/$FLASH_HELPER" from the runtime
# stone _build/tegraflash dir.
#
# That dir is populated by tegraflash-tools-deploy, which copies the *native*
# ${bindir}/tegra-flash tree. Without installing the helper here it only ever
# lands in the SDK (nativesdk-tegraflash-tools), so provisioning fails with
# ".../_build/tegraflash/tegra234-flash-helper.sh: No such file". Installing it
# via this bbappend (recipe is BBCLASSEXTEND native/nativesdk) routes it
# through -native into the runtime deploy. (S = ${UNPACKDIR}, per upstream.)
SRC_URI += " \
    file://tegra234-flash-helper.sh \
    file://nvme-pin-for-flash.sh \
"

do_install:append() {
    install -m 0755 ${S}/tegra234-flash-helper.sh ${D}${bindir}/tegra-flash/tegra234-flash-helper.sh
    # Run on the target over adb by initrd-flash (ROOTFS_NVME_PCI); it must sit
    # beside initrd-flash in the runtime copy, which comes from this -native.
    install -m 0755 ${S}/nvme-pin-for-flash.sh ${D}${bindir}/tegra-flash/nvme-pin-for-flash
}
