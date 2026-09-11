SUMMARY = "Qualcomm linux kernel UKI creation"

DESCRIPTION = "Pack kernel image as a UKI (Unified Kernel Image) \
by combining UEFI stub from systemd-boot, the kernel Image, initramfs, \
optional dtb, osrelease info and other metadata like kernel cmdline."

LICENSE = "BSD-3-Clause-Clear"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/BSD-3-Clause-Clear;md5=7a434440b651f4a472ca93716d01033a"

COMPATIBLE_HOST = '(arm.*|aarch64.*)-(linux.*)'

inherit python3native image-artifact-names linux-kernel-base

DEPENDS = " systemd-boot-native python3-native python3-pefile-native dtc-native \
            os-release systemd-boot virtual/kernel "

require conf/image-uefi.conf

KERNEL_VERSION = "${@get_kernelversion_file('${STAGING_KERNEL_BUILDDIR}')}"

do_fetch[noexec] = "1"
do_unpack[noexec] = "1"
do_patch[noexec] = "1"

SRC_URI = ""

do_configure[depends] += " \
    systemd-boot:do_deploy \
    virtual/kernel:do_deploy \
    "
do_configure[depends] += "${@ '${INITRAMFS_IMAGE}:do_image_complete' if d.getVar('INITRAMFS_IMAGE') else ''}"

do_compile() {
    # Construct the ukify command
    ukify_cmd=""

    # Ramdisk
    if [ -n "${INITRAMFS_IMAGE}" ]; then
        initrd=""
        for img in ${INITRAMFS_FSTYPES}; do
            if [ -e "${DEPLOY_DIR_IMAGE}/${INITRAMFS_IMAGE_NAME}.$img" ]; then
                initrd="${DEPLOY_DIR_IMAGE}/${INITRAMFS_IMAGE_NAME}.$img"
                break
            fi
        done
        [ -f $initrd ] && echo "Creating UKI with $initrd" || bbfatal "$initrd is not a valid initrd to create UKI."
        ukify_cmd="$ukify_cmd --initrd=$initrd"
    fi

    # Kernel Image
    # Note: systemd-boot can't handle compressed kernel image.
    kernel_image="${DEPLOY_DIR_IMAGE}/Image"
    [ -f $kernel_image ] && echo "Creating UKI with $kernel_image" || bbfatal "No valid kernel image to create UKI. Add 'Image' to KERNEL_IMAGETYPES."
    ukify_cmd="$ukify_cmd --linux=$kernel_image"

    # Kernel version
    ukify_cmd="$ukify_cmd --uname ${KERNEL_VERSION}"

    # Kernel cmdline
    if ! echo "${DISTRO_FEATURES}" | grep -q 'sota'; then
        cmdline=""
        if [ -n "${QCOM_BOOTIMG_ROOTFS}" ]; then
            cmdline="$cmdline root=${QCOM_BOOTIMG_ROOTFS} rw rootwait"
        fi

        if [ ! -z "${SERIAL_CONSOLES}" ]; then
            tmp="${SERIAL_CONSOLES}"
            console=""
            for entry in $tmp ; do
                baudrate=`echo $entry | sed 's/\;.*//'`
                tty=`echo $entry | sed -e 's/^[0-9]*\;//' -e 's/\;.*//'`
                console="$tty","$baudrate"n8
            done
            cmdline="$cmdline console=$console"
        fi

        if [ -n "${KERNEL_CMDLINE_EXTRA}" ]; then
            cmdline="$cmdline ${KERNEL_CMDLINE_EXTRA}"
        fi

        printf '%s' "$cmdline" > ${B}/cmdline
        ukify_cmd="$ukify_cmd --cmdline @${B}/cmdline"
    fi

    # Architecture
    ukify_cmd="$ukify_cmd --efi-arch ${EFI_ARCH}"

    # OS-release
    osrelease="${RECIPE_SYSROOT}${libdir}/os-release"
    ukify_cmd="$ukify_cmd --os-release @$osrelease"

    # Device tree, embedded so the stub installs it over the firmware's.
    #
    # The Qualcomm flow flashes ONE dtb to dtb_a and has no overlay-application
    # step, so a board needing an overlay -- the RB3 Gen 2 needs
    # qcs6490-rb3gen2-staging for its QPS615 Ethernet, and a mezzanine needs its
    # own -- could only change the device tree by reflashing. Embedding here
    # makes the device tree part of the UKI, which os_artifacts already A/Bs as
    # `file:efi:EFI/Linux/avocado-{a,b}+3.efi`, so it becomes OTA-updatable with
    # no new manifest machinery.
    #
    # sd-stub does the install: it hands the blob to EFI_DT_FIXUP_PROTOCOL for
    # memory-map fixups and installs the result as the DeviceTree configuration
    # table, replacing the one UEFI loaded. Verified present in the stub that
    # ships here -- systemd-stub 259.5, with install_embedded_devicetree,
    # devicetree_fixup and .dtb/.dtbauto handling in src/boot/devicetree.c.
    #
    # Gated on AVOCADO_UKI_DTB_OVERLAYS, NOT on QCOM_DTB_DEFAULT.
    #
    # Every qcom machine sets QCOM_DTB_DEFAULT -- rubikpi3, rb3gen2 and
    # exmp-q911 all do -- so keying off it would embed a device tree on all of
    # them at once and silently move each board from the firmware's dtb to this
    # one. That is a boot-path change, and it should be a per-machine decision
    # taken deliberately, not a side effect of adding this feature.
    #
    # So: a machine opts in by naming overlays. Machines that name none keep
    # booting the dtb UEFI loads from dtb_a, exactly as before.
    if [ -n "${AVOCADO_UKI_DTB_OVERLAYS}" ]; then
        if [ -z "${QCOM_DTB_DEFAULT}" ]; then
            bbfatal "AVOCADO_UKI_DTB_OVERLAYS is set but QCOM_DTB_DEFAULT is not; there is no base dtb to merge onto."
        fi
        base_dtb="${DEPLOY_DIR_IMAGE}/${QCOM_DTB_DEFAULT}.dtb"
        if [ ! -f "$base_dtb" ]; then
            bbfatal "QCOM_DTB_DEFAULT=${QCOM_DTB_DEFAULT} but $base_dtb does not exist."
        fi
        uki_dtb="${B}/uki-devicetree.dtb"
        rm -f "$uki_dtb"
        if true; then
            overlays=""
            for ovl in ${AVOCADO_UKI_DTB_OVERLAYS}; do
                ovl_path="${DEPLOY_DIR_IMAGE}/$ovl.dtbo"
                if [ ! -f "$ovl_path" ]; then
                    bbfatal "AVOCADO_UKI_DTB_OVERLAYS names $ovl but $ovl_path does not exist. Add it to KERNEL_DEVICETREE."
                fi
                overlays="$overlays $ovl_path"
            done
            echo "Merging device tree overlays into the UKI:$overlays"
            # Fails closed: a silently unapplied overlay is a board that boots
            # and is missing whatever the overlay described.
            fdtoverlay -i "$base_dtb" -o "$uki_dtb" $overlays \
                || bbfatal "fdtoverlay failed merging$overlays onto $base_dtb"
        else
            cp "$base_dtb" "$uki_dtb"
        fi
        echo "Creating UKI with devicetree $uki_dtb"
        ukify_cmd="$ukify_cmd --devicetree=$uki_dtb"
    fi

    # Stub
    stub="${DEPLOY_DIR_IMAGE}/linux${EFI_ARCH}.efi.stub"
    [ -f $stub ] && echo "Creating UKI with $stub" || bbfatal "$stub is not a valid stub to create UKI."
    ukify_cmd="$ukify_cmd --stub $stub"

    # Output
    mkdir -p "${B}${EFI_UKI_PATH}"
    output="${B}${EFI_UKI_PATH}/${EFI_LINUX_IMG}"
    rm -f $output
    ukify_cmd="$ukify_cmd --output=$output"

    # Call ukify to generate uki.
    echo "ukify cmd:$ukify_cmd"
    ukify build $ukify_cmd
}
do_compile[vardeps] += "KERNEL_CMDLINE_EXTRA QCOM_BOOTIMG_ROOTFS AVOCADO_UKI_DTB_OVERLAYS QCOM_DTB_DEFAULT"

do_install() {
    install -Dm 0755 ${B}${EFI_UKI_PATH}/${EFI_LINUX_IMG} ${D}${EFI_UKI_PATH}/${EFI_LINUX_IMG}
}

inherit deploy

do_deploy() {
    install ${B}${EFI_UKI_PATH}/${EFI_LINUX_IMG} ${DEPLOY_DIR_IMAGE}/${EFI_LINUX_IMG}
    # Also under the fixed names the stone manifest declares as images.uki_a /
    # images.uki_b, so an OS update can carry the boot entry as its own
    # artifact. One per rootfs slot: the avocado-build hook replaces each with
    # an entry whose root= names that slot's partition, but stone validates and
    # bundles during the Yocto build too, long before any project exists, and
    # an artifact the manifest references has to be present both times.
    #
    # These copies are the machine's own default -- the kernel from the default
    # multiconfig, with the machine's root= -- which is the right thing for a
    # bundle built without a project.
    install ${B}${EFI_UKI_PATH}/${EFI_LINUX_IMG} ${DEPLOY_DIR_IMAGE}/uki_a.efi
    install ${B}${EFI_UKI_PATH}/${EFI_LINUX_IMG} ${DEPLOY_DIR_IMAGE}/uki_b.efi
}

FILES:${PN} = "${EFI_UKI_PATH}/${EFI_LINUX_IMG}"

PACKAGE_ARCH = "${MACHINE_ARCH}"

SKIP_RECIPE[linux-qcom-uki] ?= "${@bb.utils.contains('KERNEL_IMAGETYPES', 'Image', '', 'systemd-boot needs uncompressed kernel image. Add "Image" to KERNEL_IMAGETYPES.', d)}"

addtask deploy after do_compile
