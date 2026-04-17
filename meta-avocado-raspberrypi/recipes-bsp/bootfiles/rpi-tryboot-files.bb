SUMMARY = "RPi tryboot A/B boot configuration files"
DESCRIPTION = "Generates autoboot.txt and tryboot.txt for the RPi EEPROM \
tryboot A/B boot mechanism. autoboot.txt selects the active boot partition; \
tryboot.txt redirects to the inactive partition for one-shot trial boots."
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

inherit deploy

# Only meaningful for tryboot-capable targets (Pi 4/5 family)
COMPATIBLE_MACHINE = "raspberrypi4|raspberrypi5|fr202|reterminal"

do_compile() {
    # Default autoboot.txt: boot from partition 1 (slot A)
    cat > ${WORKDIR}/autoboot.txt << 'EOF'
[all]
boot_partition=1
EOF

    # Default tryboot.txt: redirect to partition 2 (slot B)
    # This is overwritten by avocadoctl at OTA activation time.
    cat > ${WORKDIR}/tryboot.txt << 'EOF'
[tryboot]
boot_partition=2
EOF
}

do_deploy() {
    install -d ${DEPLOYDIR}/${BOOTFILES_DIR_NAME}
    install -m 0644 ${WORKDIR}/autoboot.txt ${DEPLOYDIR}/${BOOTFILES_DIR_NAME}/autoboot.txt
    install -m 0644 ${WORKDIR}/tryboot.txt ${DEPLOYDIR}/${BOOTFILES_DIR_NAME}/tryboot.txt
}

addtask deploy after do_compile before do_build

# These are deploy-only files, no rootfs installation needed
ALLOW_EMPTY:${PN} = "1"
