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

# Make the rootfs *be* the ESP: /EFI/... at the top level.
#
# UEFI reads an ESP's root for \EFI\BOOT\BOOTAA64.EFI and \EFI\Linux\*.efi, but
# both packages install a level down -- linux-avocado-qcom-uki into
# /boot/EFI/Linux, systemd-boot into /boot/EFI/BOOT. oe_mkvfatfs copies
# ${IMAGE_ROOTFS}/*, so without this the payloads land under a /boot directory
# on the partition, beside the empty /bin, /lib, /usr and /var the package file
# lists drag in. UEFI finds nothing bootable, prints
#
#   [QcomBds] Removable boot path
#
# and stops there with no kernel handoff.
#
# Done as a rootfs postprocess rather than by overriding IMAGE_CMD:vfat,
# because that override cannot win from a recipe: image.bbclass pulls
# image_types.bbclass in via `inherit_defer ${IMGCLASSES}` (image.bbclass:25),
# and a deferred inherit is parsed AFTER the recipe body -- so the class's
# `IMAGE_CMD:vfat = "oe_mkvfatfs ${EXTRA_IMAGECMD}"` lands on top of anything
# the recipe sets. (Confirmed against a build: PACKAGE_INSTALL from this file
# reached the task's sigdata while IMAGE_CMD:vfat still read the class value.)
esp_promote_boot() {
    [ -d ${IMAGE_ROOTFS}/boot ] || return 0
    tmp="${WORKDIR}/esp-promote"
    rm -rf "$tmp"
    mv ${IMAGE_ROOTFS}/boot "$tmp"
    # Everything outside /boot is packaging residue -- empty dirs from the file
    # lists -- and has no meaning on an EFI system partition.
    find ${IMAGE_ROOTFS} -mindepth 1 -maxdepth 1 -exec rm -rf {} +
    find "$tmp" -mindepth 1 -maxdepth 1 -exec mv -t ${IMAGE_ROOTFS} {} +
    rmdir "$tmp"
}
ROOTFS_POSTPROCESS_COMMAND += "esp_promote_boot;"

ROOTFS_SIZE ?= "614400"
IMAGE_ROOTFS_EXTRA_SPACE = "444000"

LINGUAS_INSTALL = ""
