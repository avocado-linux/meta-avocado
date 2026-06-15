# Depend on whichever bootloader the machine selects (u-boot-imx for the NXP
# EVK/FRDM, u-boot-compulab for CompuLab, u-boot-variscite for Variscite), not a
# hardcoded recipe -- forcing u-boot-imx on those fails (no defconfig for it).
# Use virtual/bootloader, which resolves via PREFERRED_PROVIDER_virtual/bootloader
# (set per-machine). NOTE: do NOT use ${IMX_DEFAULT_BOOTLOADER} here --
# imx-base.inc pins IMX_DEFAULT_BOOTLOADER:mx8 = "u-boot-imx" as an override-form
# assignment, which beats a plain machine-conf assignment regardless of order, so
# it resolves to u-boot-imx even when the real provider is u-boot-variscite.
do_compile[depends] += "virtual/bootloader:do_deploy"
do_compile[depends] += "imx-boot:do_deploy"

DEPENDS += " jq-native mkfat-native fwup-native"

SRC_URI += " \
    file://rootdisk.conf \
"

SRC_URI:append:stone-uuu-emmc = " \
    file://stone-provision-uuu-emmc.sh \
"

do_deploy:append() {
  install -d ${DEPLOYDIR}
  install -m 0644 ${WORKDIR}/rootdisk.conf ${DEPLOYDIR}/rootdisk.conf
}

do_deploy:append:stone-uuu-emmc() {
  install -d ${DEPLOYDIR}
  install -m 0755 ${WORKDIR}/stone-provision-uuu-emmc.sh ${DEPLOYDIR}/stone-provision-uuu-emmc.sh
}
