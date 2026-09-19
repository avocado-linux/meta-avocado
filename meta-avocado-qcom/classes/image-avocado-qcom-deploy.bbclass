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
# The FIT branch below builds dtb.bin around ${DEPLOY_DIR_IMAGE}/qclinuxfitImage,
# which the kernel's do_generate_qcom_fitimage produces (only when dtb-fit-image
# is in KERNEL_CLASSES). do_deploy_fixup is nostamp, so without an explicit
# dependency it can run before that task has deployed the FIT and then silently
# fall through to the legacy raw dtb -- which on this board intermittently bricks
# UEFI. Depend on it so the FIT is always present when enabled.
do_deploy_fixup[depends] += "${@'virtual/kernel:do_generate_qcom_fitimage' if 'dtb-fit-image' in (d.getVar('KERNEL_CLASSES') or '').split() else ''}"
# mkfs.vfat/mcopy: build the FIT dtb.bin FAT (qclinux_fit.img + fallback)
do_deploy_fixup[depends] += "mtools-native:do_populate_sysroot dosfstools-native:do_populate_sysroot"
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
    # When the machine builds a FIT device tree (KERNEL_CLASSES +=
    # "dtb-fit-image" -> DEPLOY_DIR_IMAGE/qclinuxfitImage), assemble dtb.bin as
    # a FAT whose root holds \qclinux_fit.img. UEFI's DtPlatformLoadDtbBlob
    # loads that and does FIT-based DT selection, which SKIPS the legacy
    # combined-dtb.dtb path whose BoardInfoDxe qcom,platform-parts-info fixup
    # intermittently reads an uninitialised pointer, faults into XBL dload
    # (05c6:900e) and bricks the board -- unrecoverable without a physical EDL
    # power cycle. Bench-measured on rb3gen2: ~65% of boots brick on the legacy
    # path vs 0/20 with the FIT.
    #
    # meta-qcom's own switch for this is QCOM_DTB_DEFAULT="multi-dtb" (see
    # linux-qcom-dtbbin.bbclass), but we cannot use it: linux-avocado-qcom-uki.bb
    # reads ${QCOM_DTB_DEFAULT}.dtb as the base for the UKI's embedded tree, so
    # QCOM_DTB_DEFAULT must stay the real board dtb. dtb-fit-image still builds
    # qclinuxfitImage on its own, so we fold it into dtb.bin here instead.
    #
    # combined-dtb.dtb is copied into the SAME FAT as a fail-safe: UEFI tries
    # \qclinux_fit.img first and only falls back to \combined-dtb.dtb if the FIT
    # is ever unreadable, so a bad FIT degrades to the old behaviour instead of
    # a hard brick. mkfs geometry must match the board's UEFI FAT driver
    # (QCOM_VFAT_SECTOR_SIZE, 4096 on UFS parts).
    #
    # Gate on KERNEL_CLASSES (set in machine conf, the single source of truth),
    # NOT on the presence of qclinuxfitImage. DEPLOY_DIR_IMAGE is never pruned,
    # so a file test would keep folding in a STALE FIT after the machine turns
    # the class off, and would silently fall through to the bricking legacy dtb
    # if the FIT were missing. When the class is on the FIT must be present --
    # fail the build rather than ship a bricking image (same fail-closed
    # contract linux-avocado-qcom-uki.bb uses for its base dtb). NEVRA note: if
    # this recipe's staged bootfiles change, bump PR:<machine> in avocado-img-ufs.bb.
    if ${@bb.utils.contains('KERNEL_CLASSES', 'dtb-fit-image', 'true', 'false', d)}; then
        if [ ! -f ${DEPLOY_DIR_IMAGE}/qclinuxfitImage ]; then
            bbfatal "dtb-fit-image is enabled but ${DEPLOY_DIR_IMAGE}/qclinuxfitImage is missing;" \
                    "staging the legacy dtb here would ship the UEFI path that bricks this board."
        fi

        # Size the FAT to the legacy dtb vfat linux-qcom-dtbbin builds: its size
        # IS meta-qcom's DTBBIN_SIZE, so this tracks a DTBBIN_SIZE bump without
        # reaching into the kernel recipe's datastore (DTBBIN_SIZE is ?= in a
        # KERNEL class and is not visible here). Fall back to 4 MiB if the legacy
        # vfat is absent (then there is no fallback dtb to fold in either).
        legacy_vfat="${DEPLOY_DIR_IMAGE}/dtb-${QCOM_DTB_DEFAULT}-image.vfat"
        if [ -n "${QCOM_DTB_DEFAULT}" ] && [ -f "$legacy_vfat" ]; then
            legacy_bytes=$(stat -c %s "$legacy_vfat")
            dtbbin_kib=$(expr "$legacy_bytes" / 1024)
        else
            dtbbin_kib=4096
            legacy_vfat=""
        fi

        # Stage the payload files: the FIT, plus the legacy combined-dtb.dtb
        # fallback lifted out of the vfat linux-qcom-dtbbin built. Normalise
        # their mtimes to SOURCE_DATE_EPOCH so the FAT is byte-reproducible
        # (mcopy -m preserves the mtime we set); without this the nostamp task
        # would publish a different archive under the same avocado-img-ufs NEVRA
        # every build. combined-dtb.dtb is the fail-safe: UEFI tries
        # \qclinux_fit.img first and only falls back to it if the FIT is
        # unreadable, so a bad FIT degrades to the old behaviour, not a brick.
        epoch="${SOURCE_DATE_EPOCH}"; [ -n "$epoch" ] || epoch=315532800
        cp ${DEPLOY_DIR_IMAGE}/qclinuxfitImage qclinux_fit.img
        touch -d @$epoch qclinux_fit.img
        if [ -n "$legacy_vfat" ]; then
            mcopy -i "$legacy_vfat" ::/combined-dtb.dtb combined-dtb.dtb
            touch -d @$epoch combined-dtb.dtb
        fi

        # Fail with a clear message if the payload will not fit, rather than let
        # mcopy die with a disk-full error that does not name this file. Sum the
        # actual payload FILE sizes (not the 4 MiB source vfat).
        budget=$(expr "$dtbbin_kib" \* 1024)
        need=$(stat -c %s qclinux_fit.img)
        if [ -f combined-dtb.dtb ]; then
            comb_bytes=$(stat -c %s combined-dtb.dtb)
            need=$(expr "$need" + "$comb_bytes")
        fi
        limit=$(expr "$budget" - 65536)
        if [ "$need" -gt "$limit" ]; then
            bbfatal "FIT dtb.bin payload needs ~${need} bytes but the ${dtbbin_kib} KiB FAT budget" \
                    "(minus ~64 KiB overhead) is ${limit} bytes. Raise DTBBIN_SIZE in" \
                    "linux-qcom-dtbbin, or shrink the device trees / overlay set."
        fi

        # Deterministic FAT: fixed volume id (mkfs.vfat -i) + preserved mtimes.
        rm -f dtb.bin
        mkfs.vfat -S ${QCOM_VFAT_SECTOR_SIZE} -i 00000000 -C dtb.bin ${dtbbin_kib}
        mcopy -m -i dtb.bin qclinux_fit.img ::/qclinux_fit.img
        [ -f combined-dtb.dtb ] && mcopy -m -i dtb.bin combined-dtb.dtb ::/combined-dtb.dtb
        rm -f qclinux_fit.img combined-dtb.dtb
    # Legacy staging for machines without a FIT. meta-qcom's multi-dtb
    # `dtb-qcom-image` recipe deploys dtb-qcom-image-${MACHINE}.rootfs.vfat,
    # while a machine that pins one dtb through QCOM_DTB_DEFAULT gets
    # linux-qcom-dtbbin's dtb-${QCOM_DTB_DEFAULT}-image.vfat.
    elif [ -f ${DEPLOY_DIR_IMAGE}/dtb-qcom-image-${MACHINE}.rootfs.vfat ]; then
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
