# imx-boot deploys its build inputs (DDR firmware, SPL, u-boot-nodtb, the
# U-Boot control DTB, bl31/tee, mkimage_fit_atf.sh) plus the host-side
# mkimage_imx8 binary into DEPLOY_DIR_IMAGE/imx-boot-tools/. The inputs are
# exactly what a project needs to re-assemble imx-boot after injecting its own
# FIT public key into that DTB (fdt_add_pubkey + nativesdk-imx-mkimage-tools),
# so ship the directory - but not the binary: it is a build-host executable
# with an RPATH into the build tree, which fails do_package_qa, and the SDK
# gets a proper one from nativesdk-imx-mkimage-tools instead.
do_install:append() {
    rm -f ${D}/imx-boot-tools/mkimage_imx8
}

# Re-keying a prebuilt imx-boot (project FIT key into the U-Boot control DTB,
# then the same soc.mak targets the distro ran) is a fixed procedure; what
# varies per machine is a handful of facts the recipe knows and a project
# cannot guess. Ship the procedure and write the facts next to it, so `avocado
# build` can run it whenever a runtime sets signing.fit_key.
#
# The family picks the procedure's branch: i.MX8M packs SPL + a U-Boot FIT;
# i.MX9 packs AHAB containers (the ELE firmware, SPL+DDR, then U-Boot with
# TF-A and OP-TEE). i.MX94/95 are left out: their containers also carry the
# System Manager and OEI images, which imx-boot-tools does not ship.
AVOCADO_REKEY_IMX_FAMILY = ""
AVOCADO_REKEY_IMX_FAMILY:mx8m-generic-bsp = "imx8m"
AVOCADO_REKEY_IMX_FAMILY:mx91-generic-bsp = "imx9"
AVOCADO_REKEY_IMX_FAMILY:mx93-generic-bsp = "imx9"
FILESEXTRAPATHS:prepend := "${THISDIR}/avocado-img-bootfiles:"
SRC_URI:append = " file://rekey-imx-boot.sh"
# The base recipe fetches nothing, so it never needed S; with a file:// entry
# do_unpack looks for ${UNPACKDIR}/${BP} and warns. The script lands in
# ${UNPACKDIR} directly.
S = "${UNPACKDIR}"
# An if-block, not an early return: the do_install appends below this one run
# in the same shell function.
do_install:append() {
    if [ -n "${AVOCADO_REKEY_IMX_FAMILY}" ]; then
        uboot_cfg="${@d.getVar('UBOOT_CONFIG').split()[0]}"
        install -m 0755 ${UNPACKDIR}/rekey-imx-boot.sh ${D}/imx-boot-tools/rekey-imx-boot.sh
        cat > ${D}/imx-boot-tools/rekey.env <<EOF
FAMILY="${AVOCADO_REKEY_IMX_FAMILY}"
MACHINE="${MACHINE}"
SOC="${IMX_BOOT_SOC_TARGET}"
UBOOT_CONFIG_EXTRA="$uboot_cfg"
UBOOT_DTB_NAME="${UBOOT_DTB_NAME}"
IMXBOOT_TARGETS="${IMXBOOT_TARGETS}"
DDR_FIRMWARE_NAME="${DDR_FIRMWARE_NAME}"
MKIMAGE_ARGS="${@'REV=' + d.getVar('IMX_SOC_REV_UPPER') if d.getVar('IMX_SOC_REV_UPPER') else ''}"
EOF
        if [ "${AVOCADO_REKEY_IMX_FAMILY}" = imx9 ]; then
            # i.MX9's imx-boot takes the combined u-boot.bin, so imx-boot-tools
            # lacks its two halves; ship them under the names the i.MX8M
            # imx-boot deploys (the re-key puts the key in the DTB and joins
            # them again). The generic deploy links name the last U-Boot
            # config built: one config on these machines.
            install -m 0644 ${DEPLOY_DIR_IMAGE}/u-boot-nodtb.bin ${D}/imx-boot-tools/u-boot-nodtb.bin-${MACHINE}-$uboot_cfg
            install -m 0644 ${DEPLOY_DIR_IMAGE}/u-boot.dtb ${D}/imx-boot-tools/u-boot.dtb-${MACHINE}-$uboot_cfg
        fi
    fi
}
do_install[vardeps] += "AVOCADO_REKEY_IMX_FAMILY IMX_BOOT_SOC_TARGET UBOOT_CONFIG UBOOT_DTB_NAME IMXBOOT_TARGETS DDR_FIRMWARE_NAME IMX_SOC_REV_UPPER"

# The collect task scrapes DEPLOY_DIR_IMAGE, so its signature must carry the
# recipes that put the bootloader there or a U-Boot change never invalidates
# this package: observed on imx8mp-evk, where u-boot-imx rebuilt with a new
# CONFIG_SYS_BOOTM_LEN and imx-boot redeployed, but avocado-img-bootfiles was
# restored from sstate carrying the previous imx-boot - so `avocado provision`
# kept flashing the old bootloader and the board stayed in its boot loop. The
# avocado-stone:do_deploy dependency above does not carry this edge (that task
# is nostamp). Same recipe set avocado-stone.bbappend depends on, for the same
# reason: virtual/bootloader, not a hardcoded u-boot-imx, so CompuLab and
# Variscite boards are covered too.
do_collect_artifacts[depends] += "virtual/bootloader:do_deploy imx-boot:do_deploy"

# Every i.MX stone manifest names a rootfs dm-verity hash image (rootfs_hash ->
# avocado-image-rootfs-<machine>.verity) for the per-slot hash partitions, and
# avocado-stone.bbappend deploys a 4096-byte zero placeholder for it. The
# collector above never ships it: the default skip list ("rootfs initramfs
# var. -var-") matches the "rootfs" in its name, so a project whose CLI does
# not yet write the placeholder itself (rootfs.image.verity landed in
# avocado-cli after 1.0.0-rc.2) fails `stone bundle` with "Image file
# 'avocado-image-rootfs-imx95-frdm.verity' for artifact 'rootfs_hash' not
# found in any input directory". Install it explicitly; a CLI that does emit
# the real hash tree writes it to the same path and simply replaces this.
do_install:append() {
    if [ -f ${DEPLOY_DIR_IMAGE}/avocado-image-rootfs-${MACHINE_SHORT_NAME}.verity ]; then
        install -m 0644 ${DEPLOY_DIR_IMAGE}/avocado-image-rootfs-${MACHINE_SHORT_NAME}.verity ${D}/
    fi
}
