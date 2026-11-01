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

# u-boot-common.inc gained `DEPENDS += "bison-native efitools-native"` in the
# 2026-09 layer bump. efitools is only packaged in meta-imx/meta-imx-sdk, which
# Avocado deliberately does not include, so the dependency is unbuildable here
# and fails the whole target at parse:
#   Nothing PROVIDES 'efitools-native' ... required by u-boot-variscite.bb
# The only consumer is the EFI capsule ESL step, which avocado.cfg turns off
# (see CONFIG_EFI_CAPSULE_AUTHENTICATE there) because capsule update is not how
# Avocado updates these boards. Dropping the dep and the feature together beats
# pulling in the whole SDK layer for one native tool. If a Variscite board ever
# needs capsule authentication, add meta-imx-sdk and revert BOTH changes.
DEPENDS:remove = "efitools-native"

# NOTE: there is deliberately no UBOOT_DEFCONFIG / do_configure:append here.
# Listing avocado.cfg and env-mmc.cfg in SRC_URI is sufficient -- cml1.bbclass
# collects the .cfg entries and u-boot.inc merges them with
# `merge_config.sh -m -O <builddir> .config <fragments>` before oldconfig.
# An earlier `cat ... >> ${S}/configs/${UBOOT_DEFCONFIG}` ran *after* that merge,
# so it never affected the build: on imx8mp-var-dart UBOOT_CONFIG[sd] is
# "imx8mp_var_dart_config" (a make alias, not a file -- make maps it to
# configs/imx8mp_var_dart_defconfig) so it only created a stray file, and on
# imx95-var-dart it appended the fragments into the vendor's real defconfig
# again on every configure. Verified in the built .config: CONFIG_ENV_OFFSET,
# CONFIG_ENV_REDUNDANT, CONFIG_ENV_OFFSET_REDUND and CONFIG_ENV_IS_IN_MMC all
# arrive via merge_config.sh alone.

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
