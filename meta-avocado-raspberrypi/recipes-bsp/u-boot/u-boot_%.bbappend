FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"
FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}/env:"
FILESEXTRAPATHS:prepend := "${@':'.join(['%s/recipes-bsp/u-boot/files' % layer for layer in d.getVar('BBLAYERS').split() if 'meta-raspberrypi' in layer])}:"

SRC_URI:append = " \
  file://maxsize.cfg \
  file://avocado.cfg \
  file://env-fat-sd.cfg \
"

# Enable NVMe support for Raspberry Pi 5 (has PCIe)
# env-fat-nvme.ubootenv uses .ubootenv extension so find_cfgs() does not
# merge it into the default build — only the variant build picks it up.
SRC_URI:append:raspberrypi5 = " \
  file://nvme.cfg \
  file://env-fat-nvme.ubootenv \
"

# Enable SATA/AHCI support for FR202 (CM4 with PCIe-to-SATA bridge)
SRC_URI:append:fr202 = " \
  file://sata.cfg \
  file://env-fat-usb.ubootenv \
"

MKENVIMAGE_EXTRA_ARGS = "-r"

# Build additional U-Boot variants for non-SD storage targets.
# The default build uses env-fat-sd.cfg (SD/eMMC, both use mmc interface).
# Additional variants are built for USB and NVMe env interfaces.
# Provisioning scripts select the correct variant at flash time by
# replacing kernel8.img on the boot partition.
UBOOT_ENV_VARIANTS ?= ""
UBOOT_ENV_VARIANTS:fr202 = "usb"
UBOOT_ENV_VARIANTS:raspberrypi5 = "nvme"

do_compile:append() {
    for variant in ${UBOOT_ENV_VARIANTS}; do
        bbnote "Building U-Boot variant for env-fat-${variant}"
        variant_builddir="${B}/variant-${variant}"
        mkdir -p "${variant_builddir}"

        # Start from the default defconfig
        oe_runmake -C ${S} O=${variant_builddir} ${UBOOT_MAKE_OPTS} ${UBOOT_MACHINE}

        # Merge all cfg fragments EXCEPT any env-fat-*.cfg, then add the variant env cfg
        variant_cfgs=""
        for cfg in ${@" ".join(find_cfgs(d))}; do
            case "$cfg" in
                *env-fat-*.cfg) ;; # skip ALL env-fat config fragments
                *) variant_cfgs="$variant_cfgs $cfg" ;;
            esac
        done
        variant_cfgs="$variant_cfgs ${WORKDIR}/env-fat-${variant}.ubootenv"

        merge_config.sh -m -O ${variant_builddir} ${variant_builddir}/.config $variant_cfgs
        oe_runmake -C ${S} O=${variant_builddir} ${UBOOT_MAKE_OPTS} oldconfig
        oe_runmake -C ${S} O=${variant_builddir} ${UBOOT_MAKE_OPTS} ${UBOOT_MAKE_TARGET}
    done
}

do_deploy:append() {
    for variant in ${UBOOT_ENV_VARIANTS}; do
        variant_builddir="${B}/variant-${variant}"
        if [ -f "${variant_builddir}/${UBOOT_BINARY}" ]; then
            install -Dm 0644 "${variant_builddir}/${UBOOT_BINARY}" \
                "${DEPLOYDIR}/u-boot-${variant}.${UBOOT_SUFFIX}"
            bbnote "Deployed U-Boot variant: u-boot-${variant}.${UBOOT_SUFFIX}"
        fi
    done
}
