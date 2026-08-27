DESCRIPTION = "EFI System Partition Image to boot Qualcomm boards"
LICENSE = "BSD-3-Clause-Clear"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/BSD-3-Clause-Clear;md5=7a434440b651f4a472ca93716d01033a"

COMPATIBLE_HOST = '(x86_64.*|arm.*|aarch64.*)-(linux.*)'

# systemd-boot ships only /boot/EFI/BOOT/bootaa64.efi -- the loader UEFI runs
# off the removable path -- and linux-avocado-qcom-uki the UKI it boots.
#
# systemd-bootconf is deliberately absent. It contributes OE's generated
# /boot/loader/{loader.conf,entries/boot.conf}, and that entry does not
# describe this board:
#
#     title boot
#     linux /Image                     <- no /Image on the ESP; we ship a UKI
#     options LABEL=boot  root=/dev/sda2   <- not this board's rootfs either
#
# with `default boot.conf` and `timeout 10` in loader.conf, so systemd-boot
# would sit for ten seconds and then fail into a nonexistent kernel. A UKI in
# /EFI/Linux is auto-discovered as a boot entry, and its cmdline is baked in by
# ukify (QCOM_BOOTIMG_ROOTFS + SERIAL_CONSOLES + KERNEL_CMDLINE_EXTRA), so a
# single-UKI ESP needs no loader config at all.
PACKAGE_INSTALL = " \
    linux-avocado-qcom-uki \
    systemd-boot \
"

KERNELDEPMODDEPEND = ""
KERNEL_DEPLOY_DEPEND = ""

inherit image

IMAGE_FSTYPES = "vfat"
IMAGE_FSTYPES_DEBUGFS = ""

# Build the vfat from ${IMAGE_ROOTFS}/boot, not ${IMAGE_ROOTFS}.
#
# UEFI reads an ESP's *root* for \EFI\BOOT\BOOTAA64.EFI and \EFI\Linux\*.efi,
# but both packages install a level down -- linux-avocado-qcom-uki into
# /boot/EFI/Linux, systemd-boot into /boot/EFI/BOOT, systemd-bootconf into
# /boot/loader. oe_mkvfatfs copies ${IMAGE_ROOTFS}/*, which puts all of that
# under a /boot directory on the partition, alongside the empty /bin, /lib,
# /usr and /var the package file lists drag in. UEFI then finds nothing
# bootable, reports
#
#   [QcomBds] Removable boot path
#
# and stops there with no kernel handoff.
#
# Mirrors oe_mkvfatfs (image_types.bbclass) with the source directory changed;
# overriding the command rather than reshaping the rootfs keeps do_rootfs and
# everything derived from it (manifest, SPDX, QA) seeing the tree the packages
# actually installed.
IMAGE_CMD:vfat () {
    mkfs.vfat ${EXTRA_IMAGECMD} -C ${IMGDEPLOYDIR}/${IMAGE_NAME}.vfat ${ROOTFS_SIZE}
    mcopy -i "${IMGDEPLOYDIR}/${IMAGE_NAME}.vfat" -vsmpQ ${IMAGE_ROOTFS}/boot/* ::/
}

ROOTFS_SIZE ?= "614400"
IMAGE_ROOTFS_EXTRA_SPACE = "444000"

LINGUAS_INSTALL = ""
