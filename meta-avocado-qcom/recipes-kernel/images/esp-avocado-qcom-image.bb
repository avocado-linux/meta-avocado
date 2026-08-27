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

# Pack the vfat from ${IMAGE_ROOTFS}/boot, so the partition root is the ESP.
#
# UEFI reads an ESP's root for \EFI\BOOT\BOOTAA64.EFI and \EFI\Linux\*.efi, but
# both packages install a level down -- linux-avocado-qcom-uki into
# /boot/EFI/Linux, systemd-boot into /boot/EFI/BOOT. Stock oe_mkvfatfs copies
# ${IMAGE_ROOTFS}/*, which buries them under /boot on the partition next to the
# empty /bin, /lib, /usr and /var the package file lists drag in; UEFI then
# finds nothing bootable, prints "[QcomBds] Removable boot path", and stops
# with no kernel handoff.
#
# Three hooks were tried before this one; all three are recorded because each
# looks reasonable until it fails:
#
#   IMAGE_CMD:vfat -- cannot win from a recipe. image.bbclass:25 pulls
#     image_types.bbclass in with `inherit_defer ${IMGCLASSES}`, and a deferred
#     inherit is parsed AFTER the recipe body, so the class's
#     `IMAGE_CMD:vfat = "oe_mkvfatfs ${EXTRA_IMAGECMD}"` lands on top. A build's
#     sigdata showed it exactly: PACKAGE_INSTALL carried this file's edit while
#     IMAGE_CMD:vfat still read the class value.
#
#   ROOTFS_POSTPROCESS_COMMAND -- too early. rootfs-postcommands.bbclass
#     appends entries that run afterwards and expect a normal rootfs;
#     rootfs_update_timestamp died with "cannot create .../rootfs/etc/timestamp:
#     Directory nonexistent" once the reshaping had removed /etc.
#
#   IMAGE_PREPROCESS_COMMAND -- right time, wrong idea. Moving directories
#     inside a pseudo-tracked rootfs desynchronises pseudo's inode->path
#     database, and the next task to touch the tree aborts:
#     "path mismatch [2 links]: ino ... db '.../rootfs/boot/EFI/Linux'
#     req '.../rootfs/EFI/Linux'". Recovering needs `bitbake -c clean`.
#
# So leave the rootfs alone and change what gets packed. `:forcevariable` is
# last in OVERRIDES, so it outranks the class's `:vfat` no matter when the
# deferred inherit runs -- verified against bb.data_smart with OVERRIDES set
# the way image.bbclass sets it. It is unconditional rather than per-fstype,
# which is safe only because IMAGE_FSTYPES above is vfat and nothing else; add
# another type and this command would be used for it too.
esp_mkvfatfs() {
    mkfs.vfat ${EXTRA_IMAGECMD} -C ${IMGDEPLOYDIR}/${IMAGE_NAME}.vfat ${ROOTFS_SIZE}
    mcopy -i "${IMGDEPLOYDIR}/${IMAGE_NAME}.vfat" -vsmpQ ${IMAGE_ROOTFS}/boot/* ::/
}
IMAGE_CMD:forcevariable = "esp_mkvfatfs"

ROOTFS_SIZE ?= "614400"
IMAGE_ROOTFS_EXTRA_SPACE = "444000"

LINGUAS_INSTALL = ""
