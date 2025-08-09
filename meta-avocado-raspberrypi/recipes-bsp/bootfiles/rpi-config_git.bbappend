append_config_if_missing() {
    # Requires CONFIG to be set by the caller
    # Adds the line to $CONFIG only if it is not already present
    if ! grep -Fqx "$1" "$CONFIG"; then
        echo "$1" >> "$CONFIG"
    fi
}

do_deploy:append:seeed() {
    CONFIG=${DEPLOYDIR}/${BOOTFILES_DIR_NAME}/config.txt
    append_config_if_missing "dtoverlay=vc4-kms-v3d-pi4"
    append_config_if_missing "dtoverlay=dwc2,dr_mode=host"
    append_config_if_missing "enable_uart=1"
    append_config_if_missing "dtparam=spi=on"
    append_config_if_missing "initramfs avocado-image-initramfs-${MACHINE}.cpio.zst followkernel"

    if ${@'true' if 'seeed-reterminal-dm' in d.getVar('MACHINEOVERRIDES').split(':') else 'false'} \
        || ${@'true' if 'seeed-reterminal-dm-mender' in d.getVar('MACHINEOVERRIDES').split(':') else 'false'}; then
        append_config_if_missing "dtoverlay=reTerminal-DM"
        append_config_if_missing "dtparam=i2c_vc=on"
        append_config_if_missing "dtoverlay=i2c3,pins_4_5"

    elif ${@'true' if 'seeed-reterminal' in d.getVar('MACHINEOVERRIDES').split(':') else 'false'} \
        || ${@'true' if 'seeed-reterminal-mender' in d.getVar('MACHINEOVERRIDES').split(':') else 'false'} \
        || ${@'true' if 'dual-gbe-cm4' in d.getVar('MACHINEOVERRIDES').split(':') else 'false'} \
        || ${@'true' if 'dual-gbe-cm4-mender' in d.getVar('MACHINEOVERRIDES').split(':') else 'false'}; then
        append_config_if_missing "dtoverlay=i2c3,pins_4_5"
        append_config_if_missing "dtoverlay=reTerminal,tp_rotate=1"

    elif ${@'true' if 'seeed-recomputer-r100x-mender' in d.getVar('MACHINEOVERRIDES').split(':') else 'false'} \
        || ${@'true' if 'seeed-recomputer-r100x' in d.getVar('MACHINEOVERRIDES').split(':') else 'false'}; then
        append_config_if_missing "dtparam=i2c_arm=on"
        append_config_if_missing "dtoverlay=i2c1,pins_44_45"
        append_config_if_missing "dtoverlay=i2c3,pins_2_3"
        append_config_if_missing "dtoverlay=i2c6,pins_22_23"
        append_config_if_missing "dtoverlay=audremap,pins_18_19"
        append_config_if_missing "dtoverlay=reComputer-R100x,uart2"

    else
        bbdebug 1 "No target device tree specified, check your MACHINEOVERRIDES"
    fi
}
