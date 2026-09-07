DESCRIPTION = "EFI System Partition Image to boot Qualcomm boards"
LICENSE = "BSD-3-Clause-Clear"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/BSD-3-Clause-Clear;md5=7a434440b651f4a472ca93716d01033a"

COMPATIBLE_HOST = '(x86_64.*|arm.*|aarch64.*)-(linux.*)'

# systemd-boot ships only /boot/EFI/BOOT/bootaa64.efi -- the loader UEFI runs
# off the removable path -- and linux-avocado-qcom-uki the UKI it boots.
#
# systemd-bootconf is not listed, but it arrives anyway: systemd-boot carries a
# hard `Requires: virtual-systemd-bootconf`, so dnf pulls it in as a dependency
# ("Installing dependencies: systemd-bootconf" in the do_rootfs log). Its files
# are kept off the partition by esp_mkvfatfs below, which copies only
# /boot/EFI. What it contributes is OE's generated
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
# -S 4096: the UFS LUN this lands on reports 4096-byte logical blocks, and
# mkfs.vfat defaults to 512. UEFI does not care -- it reads the FAT through its
# own block layer and boots fine -- but Linux refuses the mismatch outright:
#
#   FAT-fs (sda1): logical sector size too small for device (logical sector size = 512)
#
# so the ESP could not be mounted on the running system at all. That blocks any
# file-level update of the boot path: no writing a new UKI in place, no reading
# back what is installed, and therefore no OTA of the kernel or its command
# line -- only a full raw partition rewrite over QDL. Matching the device's
# block size makes the partition mountable and is a prerequisite for the A/B
# ESP work.
ESP_SECTOR_SIZE ?= "4096"

esp_mkvfatfs() {
    mkfs.vfat -S ${ESP_SECTOR_SIZE} ${EXTRA_IMAGECMD} -C ${IMGDEPLOYDIR}/${IMAGE_NAME}.vfat ${ROOTFS_SIZE}
    # /boot/EFI only, not /boot/* -- that leaves systemd-bootconf's
    # /boot/loader (which comes in as a dependency, see above) off the
    # partition, so systemd-boot auto-discovers the UKI instead of defaulting
    # to a loader entry that names a kernel this ESP does not carry.
    mcopy -i "${IMGDEPLOYDIR}/${IMAGE_NAME}.vfat" -vsmpQ ${IMAGE_ROOTFS}/boot/EFI ::/
}
IMAGE_CMD:forcevariable = "esp_mkvfatfs"

ROOTFS_SIZE ?= "614400"
IMAGE_ROOTFS_EXTRA_SPACE = "444000"

LINGUAS_INSTALL = ""
