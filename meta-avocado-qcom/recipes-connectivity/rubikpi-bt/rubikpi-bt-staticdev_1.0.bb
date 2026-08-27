SUMMARY = "RUBIK Pi 3 Bluetooth control application (Broadcom BSA stack)"
DESCRIPTION = "Userspace Bluetooth daemon for the BCM43456 (BCM4345C5) chip on the \
RUBIK Pi 3, built around Broadcom's BSA Server Architecture rather than mainline \
BlueZ. Includes bsa_server, the rubikpi_btapp control client, the BCM4345C5 hcd \
firmware patch, and a few demo audio test files."
LICENSE = "CLOSED"
LIC_FILES_CHKSUM = ""

# Source: https://github.com/rubikpi-ai/meta-rubikpi-bsp @ 227631ce94bb
SRC_URI = "git://github.com/rubikpi-ai/rubikpi_bt_bsa_demo.git;branch=main;protocol=https"
SRCREV = "c83d8155df3a9bf381b44552a3a2500eb0c001ab"

TARGET_CXX_ARCH += "${LDFLAGS}"

do_compile() {
    make CPU=arm64 -C ${S}/src
}

do_install() {
    install -d ${D}/usr/src/rubikpi-bt-demo
    install -d ${D}/usr/src/rubikpi-bt-demo/3rdparty
    install -d ${D}/usr/src/rubikpi-bt-demo/test_files/av
    install -d ${D}/usr/src/rubikpi-bt-demo/test_files/ag
    install -d ${D}/usr/src/rubikpi-btapp
    install -d ${D}/usr/src/rubikpi-btapp/src
    install -d ${D}/usr/src/rubikpi-btapp/test_files/av
    install -d ${D}/usr/src/rubikpi-btapp/test_files/ag
    install -d ${D}${bindir}
    install -m 0755 ${S}/rubikpi_btapp ${D}${bindir}/
    install -d ${D}/lib/firmware

    cp -r ${S}/3rdparty ${D}/usr/src/rubikpi-bt-demo/3rdparty
    cp -r ${S}/app_manager ${D}/usr/src/rubikpi-btapp/app_manager
    cp -r ${S}/app_av ${D}/usr/src/rubikpi-btapp/app_av
    cp -r ${S}/app_ag ${D}/usr/src/rubikpi-btapp/app_ag
    cp -r ${S}/app_ble ${D}/usr/src/rubikpi-btapp/app_ble
    cp -r ${S}/app_opc ${D}/usr/src/rubikpi-btapp/app_opc
    cp -r ${S}/app_ops ${D}/usr/src/rubikpi-btapp/app_ops

    cp -r ${S}/src ${D}/usr/src/rubikpi-btapp/src
    cp -r ${S}/rubikpi_btapp ${D}/usr/src/rubikpi-btapp/rubikpi_btapp
    cp -r ${S}/rubikpi_btapp.conf ${D}/usr/src/rubikpi-btapp/rubikpi_btapp.conf
    cp -r ${S}/bsa_server ${D}/usr/src/rubikpi-btapp/bsa_server
    cp -r ${S}/BCM4345C5_003.006.006.1081.1154.hcd ${D}/usr/src/rubikpi-btapp/BCM4345C5_003.006.006.1081.1154.hcd
    cp -r ${S}/BCM4345C5_003.006.006.1081.1154.hcd ${D}/lib/firmware/BCM4345C5_003.006.006.1081.1154.hcd
    cp -r ${S}/2c.wav ${D}/usr/src/rubikpi-btapp/test_files/av/2c.wav
    cp -r ${S}/Remix_48K_2ch_16bit.wav ${D}/usr/src/rubikpi-btapp/test_files/av/Remix_48K_2ch_16bit.wav

    chmod 777 -R ${D}/usr/src/rubikpi-bt-demo
    chmod 777 -R ${D}/usr/src/rubikpi-btapp
}

FILES:${PN} += "/usr/src/rubikpi-bt-demo"
FILES:${PN} += "/usr/src/rubikpi-bt-demo/3rdparty"
FILES:${PN} += "/usr/src/rubikpi-btapp"
FILES:${PN} += "/usr/src/rubikpi-btapp/src"
FILES:${PN} += "/lib/firmware/BCM4345C5_003.006.006.1081.1154.hcd"

deltask do_package_qa
