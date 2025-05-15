do_deploy:append:seeed() {
    CONFIG=${DEPLOYDIR}/${BOOTFILES_DIR_NAME}/config.txt
    grep -q "^dtoverlay=vc4-kms-v3d-pi4$" $CONFIG || echo "dtoverlay=vc4-kms-v3d-pi4" >> $CONFIG
    grep -q "^dtoverlay=dwc2,dr_mode=host$" $CONFIG || echo "dtoverlay=dwc2,dr_mode=host" >> $CONFIG
    grep -q "^enable_uart=1$" $CONFIG || echo "enable_uart=1" >> $CONFIG
    grep -q "^dtparam=spi=on$" $CONFIG || echo "dtparam=spi=on" >> $CONFIG
    grep -q "^initramfs avocado-initramfs.cpio.zst followkernel$" $CONFIG || echo "initramfs avocado-initramfs.cpio.zst followkernel" >> $CONFIG

    if ${@'true' if 'seeed-reterminal-dm' in d.getVar('MACHINEOVERRIDES').split(':') else 'false'} \
        || ${@'true' if 'seeed-reterminal-dm-mender' in d.getVar('MACHINEOVERRIDES').split(':') else 'false'}; then
        grep -q "^dtoverlay=reTerminal-DM$" $CONFIG || echo "dtoverlay=reTerminal-DM" >> $CONFIG
        grep -q "^dtparam=i2c_vc=on$" $CONFIG || echo "dtparam=i2c_vc=on" >> $CONFIG
        grep -q "^dtoverlay=i2c3,pins_4_5$" $CONFIG || echo "dtoverlay=i2c3,pins_4_5" >> $CONFIG

    elif ${@'true' if 'seeed-reterminal' in d.getVar('MACHINEOVERRIDES').split(':') else 'false'} \
        || ${@'true' if 'seeed-reterminal-mender' in d.getVar('MACHINEOVERRIDES').split(':') else 'false'} \
        || ${@'true' if 'dual-gbe-cm4' in d.getVar('MACHINEOVERRIDES').split(':') else 'false'} \
        || ${@'true' if 'dual-gbe-cm4-mender' in d.getVar('MACHINEOVERRIDES').split(':') else 'false'}; then
        grep -q "^dtoverlay=i2c3,pins_4_5$" $CONFIG || echo "dtoverlay=i2c3,pins_4_5" >> $CONFIG
        grep -q "^dtoverlay=reTerminal,tp_rotate=1$" $CONFIG || echo "dtoverlay=reTerminal,tp_rotate=1" >> $CONFIG

    elif ${@'true' if 'seeed-recomputer-r100x-mender' in d.getVar('MACHINEOVERRIDES').split(':') else 'false'} \
        || ${@'true' if 'seeed-recomputer-r100x' in d.getVar('MACHINEOVERRIDES').split(':') else 'false'}; then
        grep -q "^dtparam=i2c_arm=on$" $CONFIG || echo "dtparam=i2c_arm=on" >> $CONFIG
        grep -q "^dtoverlay=i2c1,pins_44_45$" $CONFIG || echo "dtoverlay=i2c1,pins_44_45" >> $CONFIG
        grep -q "^dtoverlay=i2c3,pins_2_3$" $CONFIG || echo "dtoverlay=i2c3,pins_2_3" >> $CONFIG
        grep -q "^dtoverlay=i2c6,pins_22_23$" $CONFIG || echo "dtoverlay=i2c6,pins_22_23" >> $CONFIG
        grep -q "^dtoverlay=audremap,pins_18_19$" $CONFIG || echo "dtoverlay=audremap,pins_18_19" >> $CONFIG
        grep -q "^dtoverlay=reComputer-R100x,uart2$" $CONFIG || echo "dtoverlay=reComputer-R100x,uart2" >> $CONFIG

    else
        bbdebug 1 "No target device tree specified, check your MACHINEOVERRIDES"
    fi
}
