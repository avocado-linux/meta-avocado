FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"
FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}/env:"

# The UUU tag goes on the boot partition. For 8+, the boot partition image is
# imx-boot, so disable UUU-tagging here.
UUU_BOOTLOADER:mx8m-generic-bsp = ""

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

# Variscite's UBOOT_CONFIG[sd] = "imx8mp_var_dart_config,sdcard"; the defconfig
# we append our fragments to is the part before the comma.
UBOOT_DEFCONFIG = "imx8mp_var_dart_config"

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
