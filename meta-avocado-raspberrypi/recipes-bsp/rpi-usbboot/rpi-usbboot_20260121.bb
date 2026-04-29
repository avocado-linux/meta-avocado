SUMMARY = "Raspberry Pi usbboot tool"
DESCRIPTION = "Tool to initialize Raspberry Pi CM4 and similar devices over USB"
HOMEPAGE = "https://github.com/raspberrypi/usbboot"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://LICENSE;md5=e3fc50a88d0a364313df4b21ef20c29e"

DEPENDS += "libusb1 pkgconfig-native vim-native"

PV = "20260121"
SRC_URI = "gitsm://github.com/raspberrypi/usbboot.git;branch=master;protocol=https"
SRCREV = "36baa69fc2783d9df2ff5d28e2fb4bc179bd1d1b"


inherit nativesdk

# Pass native build variables into the make environment
# EXTRA_OEMAKE += "'BUILD_CC=${BUILD_CC}' 'BUILD_CFLAGS=${BUILD_CFLAGS}' 'BUILD_LDFLAGS=${BUILD_LDFLAGS}'"

# Project uses Make directly, no configure step needed for the build itself
# do_configure[noexec] = "1"

do_compile() {
    oe_runmake

    # Pre-generate pieeprom.bin for each recovery profile using their default boot.conf
    # This allows rpiboot to work out-of-the-box without requiring users to run update-pieeprom.sh
    for recovery_dir in recovery recovery5 secure-boot-recovery secure-boot-recovery5; do
        if [ -d "${S}/${recovery_dir}" ] && [ -f "${S}/${recovery_dir}/boot.conf" ]; then
            bbnote "Generating pieeprom.bin for ${recovery_dir}"
            cd "${S}/${recovery_dir}"
            ../tools/update-pieeprom.sh || bbwarn "Failed to generate pieeprom.bin for ${recovery_dir}"
            cd "${S}"
        fi
    done
}

do_install() {
    # Create standard directories within the staging area first
    install -d ${D}${bindir}
    install -d ${D}${datadir}/rpiboot # Corresponds to $(INSTALL_PREFIX)/share/rpiboot

    # Use the Makefile's install target, overriding INSTALL_PREFIX to respect the staging directory D
    oe_runmake install DESTDIR=${D} INSTALL_PREFIX=${D}${prefix}

    # Install additional firmware profiles not included in upstream Makefile
    # recovery - Updates the bootloader EEPROM on a Compute Module 4
    install -d ${D}${datadir}/rpiboot/recovery
    cp -r ${S}/recovery/* ${D}${datadir}/rpiboot/recovery/

    # recovery5 - Updates the bootloader EEPROM on a Raspberry Pi 5
    install -d ${D}${datadir}/rpiboot/recovery5
    cp -r ${S}/recovery5/* ${D}${datadir}/rpiboot/recovery5/

    # mass-storage-gadget - Linux mass storage gadget (alternative to mass-storage-gadget64)
    install -d ${D}${datadir}/rpiboot/mass-storage-gadget
    cp -r ${S}/mass-storage-gadget/* ${D}${datadir}/rpiboot/mass-storage-gadget/

    # secure-boot-recovery - Pi4 secure-boot bootloader flash and OTP provisioning
    install -d ${D}${datadir}/rpiboot/secure-boot-recovery
    cp -r ${S}/secure-boot-recovery/* ${D}${datadir}/rpiboot/secure-boot-recovery/

    # secure-boot-recovery5 - Pi5 secure-boot bootloader flash and OTP provisioning
    install -d ${D}${datadir}/rpiboot/secure-boot-recovery5
    cp -r ${S}/secure-boot-recovery5/* ${D}${datadir}/rpiboot/secure-boot-recovery5/

    # rpi-imager-embedded - Runs the embedded version of Raspberry Pi Imager on the target device
    install -d ${D}${datadir}/rpiboot/rpi-imager-embedded
    cp -r ${S}/rpi-imager-embedded/* ${D}${datadir}/rpiboot/rpi-imager-embedded/

    # secure-boot-example - Simple Linux initrd with a UART console
    install -d ${D}${datadir}/rpiboot/secure-boot-example
    cp -r ${S}/secure-boot-example/* ${D}${datadir}/rpiboot/secure-boot-example/

    # firmware - Raspberry Pi firmware files
    install -d ${D}${datadir}/rpiboot/firmware
    cp -r ${S}/firmware/* ${D}${datadir}/rpiboot/firmware/

    # rpi-eeprom - Raspberry Pi EEPROM update files (fetched via gitsm submodule)
    install -d ${D}${datadir}/rpiboot/rpi-eeprom
    cp -r ${S}/rpi-eeprom/* ${D}${datadir}/rpiboot/rpi-eeprom/

    # tools - Scripts for updating EEPROM images (update-pieeprom.sh, etc.)
    # Required by recovery/update-pieeprom.sh and other profiles
    install -d ${D}${datadir}/rpiboot/tools
    cp -r ${S}/tools/* ${D}${datadir}/rpiboot/tools/
}

FILES:${PN} += "${datadir}/rpiboot"

# Skip QA checks for this package:
# - arch: contains target firmware (start.elf)
# - already-stripped: rpi-eeprom contains pre-stripped binaries (vl805)
INSANE_SKIP:${PN} += "arch already-stripped"

BBCLASSEXTEND = "nativesdk"
