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
    
    # Copy all tegraflash files from staging (includes binaries, configs, firmware, DTBs, etc.)
    if [ -d ${STAGING_DATADIR}/tegraflash ]; then
        bbnote "Copying all files from staging tegraflash directory"
        cp -a ${STAGING_DATADIR}/tegraflash/. ${DEPLOYDIR}/tegraflash-bsp/
        bbnote "Copied $(find ${DEPLOYDIR}/tegraflash-bsp -maxdepth 1 -type f | wc -l) files from staging"
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
    for f in ${DEPLOY_DIR_IMAGE}/uefi_jetson*.bin; do
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
    # This includes: uefi_jetson*.bin, tos*.img, eks*.img, camera*.img, nvdec*.fw, nvpva*.fw, etc.
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
ROOTFS_IMAGE="avocado-image-rootfs-${MACHINE_SHORT_NAME}.squashfs"
LNXFILE="boot.img"
EMMC_BCTS="${EMMC_BCTS}"
ODMDATA="${ODMDATA}"
FLASH_HELPER="tegra-flash-helper.sh"
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
