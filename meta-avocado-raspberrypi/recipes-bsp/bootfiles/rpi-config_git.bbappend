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
    append_config_if_missing "dtparam=audio=on"
    append_config_if_missing "disable_fw_kms_setup=1"
    append_config_if_missing "enable_uart=1"
    append_config_if_missing "disable_splash=1"
    append_config_if_missing "initramfs avocado-image-initramfs-${MACHINE_SHORT_NAME}.cpio.zst followkernel"

    if ${@'true' if 'seeed-reterminal-dm' in d.getVar('MACHINEOVERRIDES').split(':') else 'false'} \
        || ${@'true' if 'seeed-reterminal-dm-mender' in d.getVar('MACHINEOVERRIDES').split(':') else 'false'}; then
        append_config_if_missing "dtoverlay=reTerminal-DM"
        append_config_if_missing "dtparam=i2c_vc=on"
        append_config_if_missing "dtparam=i2c_arm=on"
        append_config_if_missing "dtparam=i2s=on"
        append_config_if_missing "dtparam=spi=on"
        append_config_if_missing "dtoverlay=i2c1,pins_2_3"
        append_config_if_missing "dtoverlay=i2c3,pins_4_5"
        append_config_if_missing "dtoverlay=imx219,cam0"

    elif ${@'true' if 'seeed-reterminal' in d.getVar('MACHINEOVERRIDES').split(':') else 'false'} \
        || ${@'true' if 'seeed-reterminal-mender' in d.getVar('MACHINEOVERRIDES').split(':') else 'false'} \
        || ${@'true' if 'dual-gbe-cm4' in d.getVar('MACHINEOVERRIDES').split(':') else 'false'} \
        || ${@'true' if 'dual-gbe-cm4-mender' in d.getVar('MACHINEOVERRIDES').split(':') else 'false'}; then
        append_config_if_missing "dtoverlay=i2c3,pins_4_5"
        append_config_if_missing "dtparam=ant2"
        append_config_if_missing "gpio=13=pu"
        append_config_if_missing "dtoverlay=reTerminal"

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

do_deploy:append:fr200() {
    CONFIG=${DEPLOYDIR}/${BOOTFILES_DIR_NAME}/config.txt

    # Enable the serial pins
    append_config_if_missing "enable_uart=1"

    # Config settings for OnLogic FR202 ADC
    append_config_if_missing "dtoverlay=spi4-1cs"
    append_config_if_missing "dtoverlay=spi3-1cs,cs0_pin=24"
    append_config_if_missing "dtoverlay=i2c5,pins_12_13=on,baudrate=40000"

    # Enable audio (loads snd_bcm2835)
    append_config_if_missing "dtparam=audio=on"

    # Additional overlays and parameters are documented
    # /boot/firmware/overlays/README

    # Automatically load overlays for detected cameras
    append_config_if_missing "camera_auto_detect=1"

    # Automatically load overlays for detected DSI displays
    append_config_if_missing "display_auto_detect=1"


    # Enable DRM VC4 V3D driver
    append_config_if_missing "dtoverlay=vc4-kms-v3d"
    append_config_if_missing "max_framebuffers=2"

    # Don't have the firmware create an initial video= setting in cmdline.txt.
    # Use the kernel's default instead.
    append_config_if_missing "disable_fw_kms_setup=1"

    # Disable compensation for displays with overscan
    append_config_if_missing "disable_overscan=1"

    # Run as fast as firmware / board allows
    append_config_if_missing "arm_boost=1"

    #to enable tpm SPI
    append_config_if_missing "dtoverlay=spi6-1cs,cs0_spidev=off"
    append_config_if_missing "dtoverlay=tpm-nuvoton"

    # Enable external antenna
    append_config_if_missing "dtparam=ant2"

    # Config settings specific to arm64
    append_config_if_missing "arm_64bit=1"
    append_config_if_missing "dtoverlay=dwc2"

    # User configurable settings
    append_config_if_missing "dtparam=i2c_arm=on"
    append_config_if_missing "dtoverlay=i2c1,pins_44_45=on"
    append_config_if_missing "dtoverlay=i2c-rtc,pcf85063a=on"

    append_config_if_missing "dtparam=pwr_led_trigger=backlight"
    append_config_if_missing "dtparam=pwr_led_activelow=on"
    append_config_if_missing "dtparam=eth_led0=0"
    append_config_if_missing "dtparam=eth_led1=1"
}
