FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"
FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}/env:"

# The UUU tag goes on the boot partition. On every Variscite SOM Avocado
# targets (i.MX8M Plus, i.MX95) that image is imx-boot, not the bare u-boot
# binary, so disable UUU-tagging outright rather than per SoC-family override
# -- uuu_bootloader_tag.bbclass sets it for both mx8- and mx9-generic-bsp.
UUU_BOOTLOADER = ""

SRC_URI:append:class-target = " \
  file://avocado.cfg \
  file://env-mmc.cfg \
"

# u-boot-variscite (vendor) ships a static fw_env.config; avocado owns it via
# libubootenv (runtime-generated per boot device by the avocado-uboot-env
# service; see the meta-avocado-distro libubootenv bbappend). With it in WORKDIR,
# oe-core u-boot.inc would also install it to the rootfs and deploy a bare
# DEPLOYDIR/fw_env.config symlink -- both colliding with libubootenv. Drop the
# vendor file so u-boot.inc's existence-gated install/deploy cleanly skip
# (matches the EVK/compulab, whose vendor u-boot recipes ship none).
SRC_URI:remove = "file://fw_env.config"

MKENVIMAGE_EXTRA_ARGS = "-r"

# The defconfig we append our fragments to is whatever the vendor machine conf
# named in UBOOT_CONFIG[sd], minus the optional ",<image-fstype>" suffix
# (imx8mp-var-dart: "imx8mp_var_dart_config", imx95-var-dart:
# "imx95_var_dart_defconfig"). Derived rather than hardcoded so a new Variscite
# machine cannot silently inherit another board's defconfig; one that sets no
# UBOOT_CONFIG[sd] fails loudly here instead.
UBOOT_DEFCONFIG = "${@d.getVarFlag('UBOOT_CONFIG', 'sd').split(',')[0]}"

do_configure:append:class-target () {
  cat ${UNPACKDIR}/avocado.cfg >> ${S}/configs/${UBOOT_DEFCONFIG}
  cat ${UNPACKDIR}/env-mmc.cfg >> ${S}/configs/${UBOOT_DEFCONFIG}
}

require recipes-bsp/u-boot/u-boot-env.inc

# Belt to the SRC_URI:remove suspenders: on an unclean WORKDIR a previously
# unpacked fw_env.config lingers (do_unpack doesn't scrub stale files), so
# u-boot.inc still deploys the bare DEPLOYDIR/fw_env.config symlink. Drop it
# here so the result is correct regardless of WORKDIR state -- libubootenv stays
# the sole provider. (The versioned fw_env.config-<machine>-<ver> files don't
# collide and are harmless.)
do_deploy:append() {
    rm -f ${DEPLOYDIR}/fw_env.config
}
