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

# Re-keying a prebuilt imx-boot (project FIT key into the control DTB, then the
# same soc.mak targets the distro ran) is a fixed procedure; what varies per
# machine is a handful of facts the recipe knows and a project cannot guess.
# Ship the procedure and write the facts next to it, so `avocado build` can run
# it whenever a runtime sets signing.fit_key. i.MX8M only: i.MX9 boots an AHAB
# container that is assembled and signed differently.
FILESEXTRAPATHS:prepend:mx8m-generic-bsp := "${THISDIR}/avocado-img-bootfiles:"
SRC_URI:append:mx8m-generic-bsp = " file://rekey-imx-boot.sh"
# The base recipe fetches nothing, so it never needed S; with a file:// entry
# do_unpack looks for ${UNPACKDIR}/${BP} and warns. The script lands in
# ${UNPACKDIR} directly.
S = "${UNPACKDIR}"
do_install:append:mx8m-generic-bsp() {
    install -m 0755 ${UNPACKDIR}/rekey-imx-boot.sh ${D}/imx-boot-tools/rekey-imx-boot.sh
    cat > ${D}/imx-boot-tools/rekey.env <<EOF
MACHINE="${MACHINE}"
SOC="${IMX_BOOT_SOC_TARGET}"
UBOOT_CONFIG_EXTRA="${@d.getVar('UBOOT_CONFIG').split()[0]}"
UBOOT_DTB_NAME="${UBOOT_DTB_NAME}"
IMXBOOT_TARGETS="${IMXBOOT_TARGETS}"
DDR_FIRMWARE_NAME="${DDR_FIRMWARE_NAME}"
MKIMAGE_ARGS="${@'REV=' + d.getVar('IMX_SOC_REV_UPPER') if d.getVar('IMX_SOC_REV_UPPER') else ''}"
EOF
}
do_install[vardeps] += "IMX_BOOT_SOC_TARGET UBOOT_CONFIG UBOOT_DTB_NAME IMXBOOT_TARGETS DDR_FIRMWARE_NAME IMX_SOC_REV_UPPER"

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
