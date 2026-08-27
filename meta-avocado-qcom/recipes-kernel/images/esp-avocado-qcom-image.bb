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
# Two hooks were wrong before this one, so both are recorded here.
#
# Overriding IMAGE_CMD:vfat cannot work from a recipe: image.bbclass pulls
# image_types.bbclass in via `inherit_defer ${IMGCLASSES}` (image.bbclass:25),
# and a deferred inherit is parsed AFTER the recipe body -- so the class's
# `IMAGE_CMD:vfat = "oe_mkvfatfs ${EXTRA_IMAGECMD}"` lands on top of whatever
# the recipe set. (Confirmed from a build's sigdata: PACKAGE_INSTALL carried
# this file's edit while IMAGE_CMD:vfat still read the class value.)
#
# ROOTFS_POSTPROCESS_COMMAND is too early: rootfs-postcommands.bbclass appends
# its own entries, they run after this one, and they expect a normal rootfs --
# rootfs_update_timestamp writes ${IMAGE_ROOTFS}/etc/timestamp and died with
# "Directory nonexistent" once /etc was gone.
#
# IMAGE_PREPROCESS_COMMAND is a do_image prefunc, so it runs after do_rootfs,
# the SPDX rootfs scan and do_image_qa have all seen the tree the packages
# installed, and immediately before IMAGE_CMD packs it.
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
IMAGE_PREPROCESS_COMMAND += "esp_promote_boot;"

ROOTFS_SIZE ?= "614400"
IMAGE_ROOTFS_EXTRA_SPACE = "444000"

LINGUAS_INSTALL = ""
