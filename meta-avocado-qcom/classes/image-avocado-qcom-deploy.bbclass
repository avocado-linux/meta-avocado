# Copyright (c) 2023 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

## Repurpose deploy directory to meet some general needs like retaining 'rootfs',
## generating a tar with debug symbols of all pkgs, create a directory with all
## images at one place etc.

# The work directory for image recipes is retained as the 'rootfs' directory
# can be used as sysroot during remote gdb debgging
RM_WORK_EXCLUDE += "${PN}"

# generate a companion debug archive containing symbols from the -dbg packages
IMAGE_GEN_DEBUGFS = "1"
IMAGE_FSTYPES_DEBUGFS = "tar.bz2"

# Don't install locales into rootfs
IMAGE_LINGUAS = ""

inherit python3native

DEPENDS:append = " \
    python3-native \
    qdl-native \
"

# Default Image names
BOOTIMAGE_TARGET   ?= "boot.img"
SYSTEMIMAGE_TARGET ?= "system.img"

SYSTEMIMAGE_TYPE = "squashfs"

# Place all files needed to flash the device in DEPLOY_DIR_NAME/IMAGE_BASENAME.
# As they can't be directly installed into this path from actual recipes,
# use do_deploy_fixup task and copy them here.
do_deploy_fixup[dirs] = "${DEPLOY_DIR_IMAGE}/${IMAGE_BASENAME}"
do_deploy_fixup[cleandirs] = "${DEPLOY_DIR_IMAGE}/${IMAGE_BASENAME}"
do_deploy_fixup[depends] += "esp-avocado-qcom-image:do_image_complete"
# dtb.bin (dtb_a partition): the vfat image linux-qcom-dtbbin builds around
# combined-dtb.dtb for KERNEL_DEVICETREE - the same file layout Thundercomm's
# UEFI reads that the old meta-qcom-hwe dtb-qcom-image produced from mergedtb.
do_deploy_fixup[depends] += "virtual/kernel:do_qcom_dtbbin_deploy"
do_deploy_fixup[deptask] = "do_image_complete"

DEPLOYDEPENDS = " \
    virtual/bootbins:do_deploy \
    qcom-gen-partition-bins:do_deploy \
    "
do_deploy_fixup[depends] += "${DEPLOYDEPENDS}"

do_deploy_fixup[nostamp] = "1"

# Cross-check the staged tree against what rawprogram[0-9].xml will flash.
#
# The glob is deliberately narrow, here and in the copy loop below.
# qcom-gen-partition-bins also deploys rawprogram<N>_BLANK_GPT.xml,
# rawprogram<N>_WIPE_PARTITIONS.xml and wipe_rawprogram_PHY<N>.xml -- destructive
# variants that must not reach the bootfiles bundle a normal provision flashes.
# rawprogram[0-9].xml is exactly the non-destructive set, so widening this to
# rawprogram*.xml would ship partition-wipe scripts and make this check demand
# the payloads they name.
#
# Every copy in do_deploy_fixup is guarded by `if [ -f ... ]`, so a deploy name
# that stops matching is skipped in silence. The rawprogram entry still flashes
# the file, and the miss only surfaces on hardware, tens of partitions into a
# QDL run, as `unable to open <name>...failing` -- with the device half written.
#
# Call this LAST, from the machine bbappend that finishes staging, immediately
# before the bootfiles tarball is rolled: do_deploy_fixup:append() bodies run
# after the class body, so a check placed at the end of the class would fire on
# files those appends have not copied yet.
#
# system.img and the /var image are absent by design: avocado-cli builds the
# runtime pair (extensions applied, users configured) and
# stone-provision-ufs.sh injects them at provision time.
qcom_check_rawprogram_payloads() {
    missing=""
    for rawpg in rawprogram[0-9].xml; do
        [ -f "$rawpg" ] || continue
        for required in $(sed -n 's/.*filename="\([^"]*\)".*/\1/p' "$rawpg" | sort -u); do
            case "$required" in
                ""|system.img|avocado-image-var-*) continue ;;
            esac
            if [ ! -f "$required" ]; then
                case " $missing " in
                    *" $required "*) ;;
                    *) missing="$missing $required" ;;
                esac
            fi
        done
    done
    if [ -n "$missing" ]; then
        bbfatal "rawprogram[0-9].xml flashes files this image does not stage:${missing}." \
                "Provisioning would fail mid-flash. Check the matching deploy-name" \
                "test in image-avocado-qcom-deploy.bbclass or the machine bbappend."
    fi
}

do_deploy_fixup () {
    # copy vmlinux, Image.gz/Image/zImage
    if [ -f ${DEPLOY_DIR_IMAGE}/vmlinux ]; then
        install -m 0644 ${DEPLOY_DIR_IMAGE}/vmlinux .
    fi
    if [ -f ${DEPLOY_DIR_IMAGE}/${KERNEL_IMAGETYPE} ]; then
        install -m 0644 ${DEPLOY_DIR_IMAGE}/${KERNEL_IMAGETYPE} .
    fi

    # copy boot.img
    if [ -f ${DEPLOY_DIR_IMAGE}/boot-initramfs-combined-dtb-${KERNEL_IMAGE_LINK_NAME}.img ]; then
        install -m 0644 ${DEPLOY_DIR_IMAGE}/boot-initramfs-combined-dtb-${KERNEL_IMAGE_LINK_NAME}.img ${BOOTIMAGE_TARGET}
    else
        dtbf="${KERNEL_DEVICETREE}"
        dtbf=${dtbf##*/}
        dtb_name="${dtbf%.*}"
        if [ -f ${DEPLOY_DIR_IMAGE}/boot-initramfs-$dtb_name-${KERNEL_IMAGE_LINK_NAME}.img ]; then
            install -m 0644 ${DEPLOY_DIR_IMAGE}/boot-initramfs-$dtb_name-${KERNEL_IMAGE_LINK_NAME}.img ${BOOTIMAGE_TARGET}
        fi
    fi

    # copy kernel modules
    if [ -f ${DEPLOY_DIR_IMAGE}/modules-${MODULE_TARBALL_LINK_NAME}.tgz ]; then
         install -m 0644 ${DEPLOY_DIR_IMAGE}/modules-${MODULE_TARBALL_LINK_NAME}.tgz kernel-modules.tgz
    fi

    # copy efi.bin
    if [ -f ${DEPLOY_DIR_IMAGE}/esp-avocado-qcom-image-${MACHINE}.rootfs.vfat ]; then
        install -m 0644 ${DEPLOY_DIR_IMAGE}/esp-avocado-qcom-image-${MACHINE}.rootfs.vfat efi.bin
    fi

    # copy dtb.bin -- the payload rawprogram[0-9].xml flashes to dtb_a.
    #
    # Two producers, two names. meta-qcom's multi-dtb `dtb-qcom-image` recipe
    # deploys dtb-qcom-image-${MACHINE}.rootfs.vfat, but a machine that pins a
    # single dtb through QCOM_DTB_DEFAULT (avocado-rubikpi3 does: one board,
    # one dtb, no qcom-dtb-metadata) never builds that recipe. It gets
    # linux-qcom-dtbbin's dtb-${QCOM_DTB_DEFAULT}-image.vfat instead -- the
    # same name meta-qcom's own qcom-capsule.bbclass stages as dtb.bin.
    if [ -f ${DEPLOY_DIR_IMAGE}/dtb-qcom-image-${MACHINE}.rootfs.vfat ]; then
        install -m 0644 ${DEPLOY_DIR_IMAGE}/dtb-qcom-image-${MACHINE}.rootfs.vfat dtb.bin
    elif [ -n "${QCOM_DTB_DEFAULT}" ] && \
         [ -f ${DEPLOY_DIR_IMAGE}/dtb-${QCOM_DTB_DEFAULT}-image.vfat ]; then
        install -m 0644 ${DEPLOY_DIR_IMAGE}/dtb-${QCOM_DTB_DEFAULT}-image.vfat dtb.bin
    fi

    # copy el2-dtb.bin
    if [ -f ${DEPLOY_DIR_IMAGE}/dtb-el2-qcom-image-${MACHINE}.rootfs.vfat ]; then
        install -m 0644 ${DEPLOY_DIR_IMAGE}/dtb-el2-qcom-image-${MACHINE}.rootfs.vfat el2-dtb.bin
    fi

    # The rootfs partition file (system.img) is NOT staged here. Avocado-cli
    # rebuilds the rootfs at runtime (with extensions applied + user configs),
    # so the yocto-baked rootfs would always be stale. stone-provision-ufs.sh
    # injects avocado-cli's runtime-built rootfs as system.img at provision
    # time, per the stone manifest's `images.rootfs` entry.

    #Copy gpt_main.bin
    for gmbf in ${DEPLOY_DIR_IMAGE}/gpt_main[0-9].bin; do
        if [ -f "$gmbf" ]; then
            install -m 0644 $gmbf .
        fi
    done

    #Copy gpt_backup.bin
    for gpback in ${DEPLOY_DIR_IMAGE}/gpt_backup[0-9].bin; do
        if [ -f "$gpback" ]; then
            install -m 0644 $gpback .
        fi
    done

    # Copy rawprogram.xml -- the non-destructive set only; see the note above
    # qcom_check_rawprogram_payloads for why this glob is not rawprogram*.xml.
    for rawpg in ${DEPLOY_DIR_IMAGE}/rawprogram[0-9].xml; do
        if [ -f "$rawpg" ]; then
            install -m 0644 $rawpg .
        fi
    done

    #Copy the .elf, .mbn files
    for elffile in ${DEPLOY_DIR_IMAGE}/*.elf; do
        if [ -f "$elffile" ]; then
            install -m 0644 $elffile .
        fi
    done

    for mbnfile in ${DEPLOY_DIR_IMAGE}/*.mbn; do
        if [ -f "$mbnfile" ]; then
            install -m 0644 $mbnfile .
        fi
    done

    #Copy the .melf, .fv files
    for melffile in ${DEPLOY_DIR_IMAGE}/*.melf; do
        if [ -f "$melffile" ]; then
            install -m 0644 $melffile .
        fi
    done

    for fvfile in ${DEPLOY_DIR_IMAGE}/*.fv; do
        if [ -f "$fvfile" ]; then
            install -m 0644 $fvfile .
        fi
    done

    # copy logfs_ufs_8mb.bin
    if [ -f ${DEPLOY_DIR_IMAGE}/logfs_ufs_8mb.bin ]; then
        install -m 0644 ${DEPLOY_DIR_IMAGE}/logfs_ufs_8mb.bin logfs_ufs_8mb.bin
    fi

    # copy zeros_5sectors.bin
    if [ -f ${DEPLOY_DIR_IMAGE}/zeros_5sectors.bin ]; then
        install -m 0644 ${DEPLOY_DIR_IMAGE}/zeros_5sectors.bin zeros_5sectors.bin
    fi

    # copy zeros_33sectors.bin
    if [ -f ${DEPLOY_DIR_IMAGE}/zeros_33sectors.bin ]; then
        install -m 0644 ${DEPLOY_DIR_IMAGE}/zeros_33sectors.bin zeros_33sectors.bin
    fi

    # copy fitimage
    if [ -f ${DEPLOY_DIR_IMAGE}/fitImage-combineddtb ]; then
        install -m 0644 ${DEPLOY_DIR_IMAGE}/fitImage-combineddtb boot.img
    fi 

    # copy u-boot.elf
    if [ -f ${DEPLOY_DIR_IMAGE}/u-boot.elf ]; then
        install -m 0644 ${DEPLOY_DIR_IMAGE}/u-boot.elf u-boot.elf
    fi

    for patchfile in ${DEPLOY_DIR_IMAGE}/patch*.xml; do
        if [ -f "$patchfile" ]; then
            install -m 0644 $patchfile .
        fi
    done

    # Copy sail boot bins
    if [ -d ${DEPLOY_DIR_IMAGE}/sail_nor ]; then
        install -d sail_nor
        for f in ${DEPLOY_DIR_IMAGE}/sail_nor/*; do
            install -m 0644 $f ./sail_nor/
	done
    fi

    # Copy ufs partition bins
    if [ -d ${DEPLOY_DIR_IMAGE}/partition_ufs ]; then
        install -d partition_ufs
        for f in ${DEPLOY_DIR_IMAGE}/partition_ufs/*; do
            install -m 0644 $f ./partition_ufs/
        done
    fi

    # Copy emmc partition bins
    if [ -d ${DEPLOY_DIR_IMAGE}/partition_emmc ]; then
        install -d partition_emmc
        for f in ${DEPLOY_DIR_IMAGE}/partition_emmc/*; do
            install -m 0644 $f ./partition_emmc/
        done
    fi

}
addtask do_deploy_fixup after do_image_complete before do_build
