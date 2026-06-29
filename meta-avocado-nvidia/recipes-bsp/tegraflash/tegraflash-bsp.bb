DESCRIPTION = "Tegraflash BSP files for deployment"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

COMPATIBLE_MACHINE = "(tegra)"

inherit deploy l4t_bsp

# SoC-specific file names - these mirror image_types_tegra.bbclass definitions
TOSIMGFILENAME = "tos-optee.img"
TOSIMGFILENAME:tegra234 = "tos-optee_t234.img"
EKSIMGFILENAME = "eks.img"
EKSIMGFILENAME:tegra234 = "eks_t234.img"

# Compute ROOTFS_DEVICE from TNSPEC_BOOTDEV (mirrors image_types_tegra.bbclass::tegra_rootfs_device)
def compute_rootfs_device(d):
    import re
    bootdev = d.getVar('TNSPEC_BOOTDEV') or ""
    if bootdev.startswith("mmc") or bootdev.startswith("nvme"):
        return re.sub(r"p[0-9]+$", "", bootdev)
    return re.sub("[0-9]+$", "", bootdev)

ROOTFS_DEVICE_FOR_INITRD_FLASH = "${@compute_rootfs_device(d)}"

# Flash layout size variables - these defaults mirror image_types_tegra.bbclass
LNXSIZE ?= "83886080"
TEGRA_EXTERNAL_DEVICE_SECTORS ??= "119537664"
TEGRA_INTERNAL_DEVICE_SECTORS ??= "119537664"
TEGRA_RECOVERY_KERNEL_PART_SIZE ??= "83886080"
RECROOTFSSIZE ?= "314572800"
ESP_FILE ?= "esp.img"
DATAFILE ??= ""

# Compute BOOTCONTROL_OVERLAYS the same way image_types_tegra.bbclass does
# This is a comma-separated list derived from TEGRA_BOOTCONTROL_OVERLAYS
def tegraflash_bsp_bootcontrol_overlays(d):
    overlays = d.getVar('TEGRA_BOOTCONTROL_OVERLAYS').split()
    return ','.join(overlays)

TEGRAFLASH_BSP_BOOTCONTROL_OVERLAYS = "${@tegraflash_bsp_bootcontrol_overlays(d)}"

# Depend on tegra-bootfiles and other packages to get access to BSP files
DEPENDS = "tegra-bootfiles tegra-binaries tegra-storage-layout nvidia-kernel-oot tegra-flashvars"

# This recipe just deploys files, no compilation needed
do_compile[noexec] = "1"
do_install[noexec] = "1"

# L4T source directory - construct using L4T_VERSION to match tegra-binaries
# The shared source is at work-shared/L4T-tegra-<L4T_VERSION>-r0/Linux_for_Tegra
L4T_BSP_DIR = "${TMPDIR}/work-shared/L4T-tegra-${L4T_VERSION}-r0/Linux_for_Tegra"

# Ensure L4T source is available during deploy
do_deploy[depends] += "tegra-binaries:do_preconfigure"
# Depend on edk2-firmware-tegra deploy for L4TConfiguration DTBOs
do_deploy[depends] += "edk2-firmware-tegra:do_deploy"
# Depend on initramfs for boot.img (runtime kernel+initramfs cboot)
do_deploy[depends] += "avocado-image-initramfs:do_image_complete"
# Depend on tegra-initrd-flash-initramfs for tegraflash provisioning
do_deploy[depends] += "tegra-initrd-flash-initramfs:do_image_complete"

# Deploy BSP files from the staging datadir to the images directory
# Creates both a directory (for SDK stone path) and a tarball (for stone manifest inclusion)
do_deploy() {
    install -d ${DEPLOYDIR}/tegraflash-bsp

    # Empty carrier-bsp stub. Stone manifests for SOM-style targets
    # (jetson-orin-nx, etc.) declare `tegraflash_carrier_bsp: "carrier-bsp"`
    # so that BSP extensions can contribute carrier overrides at
    # avocado-cli build time via stone_include_paths. The Yocto-time
    # `do_stone_validate` / `do_stone_bundle` tasks run against
    # ${DEPLOY_DIR_IMAGE} only and have no extension content; without
    # this stub, validation fails with "1 file(s) not found:
    # device: rootdisk, image: tegraflash_carrier_bsp -> carrier-bsp".
    #
    # The .placeholder file ensures the directory survives the sstate
    # copy from DEPLOYDIR to DEPLOY_DIR_IMAGE (some copy mechanisms drop
    # empty directories). At avocado-cli build time, the carrier
    # extension's stone_include_paths puts its own carrier-bsp/ earlier
    # in stone's `-i` search order, so the real carrier files win and
    # this stub is harmless.
    install -d ${DEPLOYDIR}/carrier-bsp
    touch ${DEPLOYDIR}/carrier-bsp/.placeholder

    # Copy all tegraflash files from staging (includes binaries, configs, firmware, DTBs, etc.)
    if [ -d ${STAGING_DATADIR}/tegraflash ]; then
        bbnote "Copying all files from staging tegraflash directory"
        cp -a ${STAGING_DATADIR}/tegraflash/. ${DEPLOYDIR}/tegraflash-bsp/
        bbnote "Copied $(find ${DEPLOYDIR}/tegraflash-bsp -maxdepth 1 -type f | wc -l) files from staging"
    fi

    # Append BOOTCONTROL_OVERLAYS to flashvars (mirrors image_types_tegra.bbclass behavior)
    # This is required for tegra-flash-helper.sh to include the correct DTB overlays,
    # including L4TConfiguration-RootfsRedundancyLevelABEnable.dtbo for rootfs A/B support
    if [ -f ${DEPLOYDIR}/tegraflash-bsp/flashvars ]; then
        sed -i -e "\$a\BOOTCONTROL_OVERLAYS=\"${TEGRAFLASH_BSP_BOOTCONTROL_OVERLAYS}\"" ${DEPLOYDIR}/tegraflash-bsp/flashvars
    fi
    
    # Copy kernel DTBs and DTBOs from nvidia-kernel-oot
    if [ -d ${STAGING_DIR_TARGET}/boot/devicetree ]; then
        # Copy all DTBs
        for f in ${STAGING_DIR_TARGET}/boot/devicetree/*.dtb; do
            if [ -f "$f" ]; then
                install -m 0644 "$f" ${DEPLOYDIR}/tegraflash-bsp/
                # Also install super DTBs as kernel_<dtbname> for flash helper scripts
                dtb_name=$(basename "$f")
                if echo "$dtb_name" | grep -q "nv-super"; then
                    install -m 0644 "$f" ${DEPLOYDIR}/tegraflash-bsp/kernel_${dtb_name}
                fi
            fi
        done
        # Copy all DTBOs
        for f in ${STAGING_DIR_TARGET}/boot/devicetree/*.dtbo; do
            [ -f "$f" ] && install -m 0644 "$f" ${DEPLOYDIR}/tegraflash-bsp/
        done
    fi
    
    # Copy L4TConfiguration DTBOs from deploy directory (produced by edk2-firmware-tegra)
    for f in ${DEPLOY_DIR_IMAGE}/L4TConfiguration*.dtbo; do
        [ -f "$f" ] && install -m 0644 "$f" ${DEPLOYDIR}/tegraflash-bsp/
    done
    
    # Copy UEFI bootloader binaries from deploy directory
    # Match both old-style (uefi_jetson*) and new-style (uefi_t23x*) naming conventions
    for f in ${DEPLOY_DIR_IMAGE}/uefi_jetson*.bin ${DEPLOY_DIR_IMAGE}/uefi_t23x*.bin; do
        [ -f "$f" ] && install -m 0644 "$f" ${DEPLOYDIR}/tegraflash-bsp/
    done
    
    # Copy devicetree directory contents from deploy (additional DTBs/DTBOs)
    if [ -d ${DEPLOY_DIR_IMAGE}/devicetree ]; then
        for f in ${DEPLOY_DIR_IMAGE}/devicetree/*.dtb ${DEPLOY_DIR_IMAGE}/devicetree/*.dtbo; do
            [ -f "$f" ] && install -m 0644 "$f" ${DEPLOYDIR}/tegraflash-bsp/
        done
    fi
    
    # Process flash.xml templates - replace placeholders that image_types_tegra.bbclass normally handles
    # These replacements mirror what happens in image_types_tegra.bbclass::copy_flash_layout()
    # Note: APPFILE, APPFILE_b, DTB_FILE, DATAFILE are replaced at flash time by initrd-flash.sh
    process_flash_xml() {
        local xmlfile="$1"
        sed -i \
            -e"s,LNXFILE_b,boot.img," \
            -e"s,LNXFILE,boot.img," -e"s,LNXSIZE,${LNXSIZE}," \
            -e"s,TOSFILE,${TOSIMGFILENAME}," \
            -e"s,EKSFILE,eks.img," \
            -e"s,APPSIZE,${ROOTFSPART_SIZE}," \
            -e"s,EXT_NUM_SECTORS,${TEGRA_EXTERNAL_DEVICE_SECTORS}," \
            -e"s,INT_NUM_SECTORS,${TEGRA_INTERNAL_DEVICE_SECTORS}," \
            -e"s,RECNAME,recovery," -e"s,RECSIZE,${TEGRA_RECOVERY_KERNEL_PART_SIZE}," -e"s,RECDTB-NAME,recovery-dtb," \
            -e"s,RECROOTFSSIZE,${RECROOTFSSIZE}," \
            -e"s,APPUUID_b,," -e"s,APPUUID,," \
            -e"s,ESP_FILE,${ESP_FILE}," \
            -e"/RECFILE/d" -e"/RECDTB-FILE/d" -e"/BOOTCTRL-FILE/d" \
            -e"/IST_UCODE/d" -e"/IST_BPMPFW/d" -e"/IST_ICTBIN/d" -e"/IST_TESTIMG/d" -e"/IST_RTINFO/d" \
            -e"/VARSTORE_FILE/d" \
            "$xmlfile"
    }
    
    if [ -f ${DEPLOYDIR}/tegraflash-bsp/internal-flash.xml ]; then
        process_flash_xml ${DEPLOYDIR}/tegraflash-bsp/internal-flash.xml
        cp ${DEPLOYDIR}/tegraflash-bsp/internal-flash.xml ${DEPLOYDIR}/tegraflash-bsp/flash.xml.in
    fi
    if [ -f ${DEPLOYDIR}/tegraflash-bsp/external-flash.xml ]; then
        process_flash_xml ${DEPLOYDIR}/tegraflash-bsp/external-flash.xml
        cp ${DEPLOYDIR}/tegraflash-bsp/external-flash.xml ${DEPLOYDIR}/tegraflash-bsp/external-flash.xml.in
    fi
    # Deploy eMMC layout variant for "build once, provision to any media"
    if [ -f ${DEPLOYDIR}/tegraflash-bsp/internal-flash-emmc.xml ]; then
        process_flash_xml ${DEPLOYDIR}/tegraflash-bsp/internal-flash-emmc.xml
    fi
    
    # Copy the generic/ directory structure from L4T source
    # The tegraflash scripts expect generic/BCT/ subdirectory for DTS includes
    if [ -d ${L4T_BSP_DIR}/bootloader/generic ]; then
        bbnote "Copying generic/ directory structure from L4T source"
        install -d ${DEPLOYDIR}/tegraflash-bsp/generic
        cp -a ${L4T_BSP_DIR}/bootloader/generic/. ${DEPLOYDIR}/tegraflash-bsp/generic/
        bbnote "Copied $(find ${DEPLOYDIR}/tegraflash-bsp/generic -type f | wc -l) files to generic/"
    else
        bbwarn "L4T generic directory not found at ${L4T_BSP_DIR}/bootloader/generic"
    fi
    
    # Copy all binaries, firmware, and images from L4T bootloader that may not be in staging
    # This includes: uefi_*.bin, tos*.img, eks*.img, camera*.img, nvdec*.fw, nvpva*.fw, etc.
    if [ -d ${L4T_BSP_DIR}/bootloader ]; then
        bbnote "Copying binaries and firmware from L4T bootloader"
        for f in ${L4T_BSP_DIR}/bootloader/*.bin; do
            [ -f "$f" ] && install -m 0644 "$f" ${DEPLOYDIR}/tegraflash-bsp/
        done
        for f in ${L4T_BSP_DIR}/bootloader/*.img; do
            [ -f "$f" ] && install -m 0644 "$f" ${DEPLOYDIR}/tegraflash-bsp/
        done
        for f in ${L4T_BSP_DIR}/bootloader/*.fw; do
            [ -f "$f" ] && install -m 0644 "$f" ${DEPLOYDIR}/tegraflash-bsp/
        done
        # Also need eks.img which tegraflash expects (SoC-specific source file)
        if [ -f ${L4T_BSP_DIR}/bootloader/${EKSIMGFILENAME} ]; then
            install -m 0644 ${L4T_BSP_DIR}/bootloader/${EKSIMGFILENAME} ${DEPLOYDIR}/tegraflash-bsp/eks.img
        fi
        bbnote "Copied L4T bootloader files"
    fi
    
    # Ensure UEFI binaries exist with the names expected by flashvars.
    # The L4T bootloader ships uefi_jetson.bin / uefi_jetson_minimal.bin (old names),
    # but flashvars now references them as uefi_t23x_general / uefi_t23x_rcmboot (new names).
    # Create copies with the new names if they don't already exist from edk2-firmware-tegra.
    if [ -f ${DEPLOYDIR}/tegraflash-bsp/uefi_jetson.bin ] && \
       [ ! -f ${DEPLOYDIR}/tegraflash-bsp/${TEGRA_FLASHVAR_UEFI_IMAGE}.bin ]; then
        cp ${DEPLOYDIR}/tegraflash-bsp/uefi_jetson.bin ${DEPLOYDIR}/tegraflash-bsp/${TEGRA_FLASHVAR_UEFI_IMAGE}.bin
        bbnote "Created ${TEGRA_FLASHVAR_UEFI_IMAGE}.bin from uefi_jetson.bin"
    fi
    if [ -f ${DEPLOYDIR}/tegraflash-bsp/uefi_jetson_minimal.bin ] && \
       [ ! -f ${DEPLOYDIR}/tegraflash-bsp/${TEGRA_FLASHVAR_RCM_UEFI_IMAGE}.bin ]; then
        cp ${DEPLOYDIR}/tegraflash-bsp/uefi_jetson_minimal.bin ${DEPLOYDIR}/tegraflash-bsp/${TEGRA_FLASHVAR_RCM_UEFI_IMAGE}.bin
        bbnote "Created ${TEGRA_FLASHVAR_RCM_UEFI_IMAGE}.bin from uefi_jetson_minimal.bin"
    fi

    # Copy boot.img (runtime kernel+initramfs cboot) for A_kernel partition
    # This is the image that will be booted after flashing completes
    if [ -f ${DEPLOY_DIR_IMAGE}/avocado-image-initramfs-${MACHINE_SHORT_NAME}.cpio.gz.cboot ]; then
        install -m 0644 ${DEPLOY_DIR_IMAGE}/avocado-image-initramfs-${MACHINE_SHORT_NAME}.cpio.gz.cboot ${DEPLOYDIR}/tegraflash-bsp/boot.img
        bbnote "Installed boot.img from avocado-image-initramfs cboot"
    else
        bbwarn "Runtime initramfs cboot not found at ${DEPLOY_DIR_IMAGE}/avocado-image-initramfs-${MACHINE_SHORT_NAME}.cpio.gz.cboot"
    fi
    
    # Generate .env.initrd-flash environment file for the provision script
    cat > ${DEPLOYDIR}/tegraflash-bsp/.env.initrd-flash <<EOF
# Environment settings for initrd-flash
# Generated by tegraflash-bsp recipe
MACHINE="${MACHINE}"
DTBFILE="${@os.path.basename(d.getVar('KERNEL_DEVICETREE').split()[0])}"
ROOTFS_IMAGE="avocado-image-rootfs-${MACHINE_SHORT_NAME}.erofs-lz4"
LNXFILE="boot.img"
EMC_BCT="${EMC_BCT}"
ODMDATA="${ODMDATA}"
CHIPID="${NVIDIA_CHIP}"
FLASH_HELPER="tegra234-flash-helper.sh"
BOOTDEV="${TNSPEC_BOOTDEV}"
ROOTFS_DEVICE="${ROOTFS_DEVICE_FOR_INITRD_FLASH}"
EXTERNAL_ROOTFS_DRIVE=${@'1' if d.getVar('TEGRAFLASH_NO_INTERNAL_STORAGE') == '1' else '0'}
NO_INTERNAL_STORAGE=${@'1' if d.getVar('TEGRAFLASH_NO_INTERNAL_STORAGE') == '1' else '0'}
DATAFILE="avocado-image-var-${MACHINE_SHORT_NAME}.btrfs"
EOF
# Note: OVERLAY_DTB_FILE and DCE_OVERLAY are in flashvars (from tegra-flashvars recipe)
}

addtask deploy before do_build after do_compile

PACKAGE_ARCH = "${MACHINE_ARCH}"
