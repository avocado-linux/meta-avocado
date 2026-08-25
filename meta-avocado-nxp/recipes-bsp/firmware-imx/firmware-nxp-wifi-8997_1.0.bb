SUMMARY = "NXP 88W8997 Wi-Fi/BT firmware, from the last NXP release that shipped it"
DESCRIPTION = "NXP removed the 88W8997 from imx-firmware (and from the moal driver) \
at 6.18. The i.MX 8M Plus EVK's stock M.2 module (AW-CM276MA) is an 88W8997, so \
this recipe carries the blobs from lf-6.12.49_2.2.0 for the mainline mwifiex \
and btnxpuart drivers. firmware-nxp-wifi at 6.18 ships no 8997 files, so the \
two packages do not collide."
HOMEPAGE = "https://github.com/nxp-imx/imx-firmware"
SECTION = "kernel"
LICENSE = "Proprietary"
LIC_FILES_CHKSUM = "file://LICENSE.txt;md5=bc649096ad3928ec06a8713b8d787eac"

SRC_URI = "git://github.com/nxp-imx/imx-firmware.git;protocol=https;branch=lf-6.12.49_2.2.0"
SRCREV = "8c9b278016c97527b285f2fcbe53c2d428eb171d"

inherit allarch
do_compile[noexec] = "1"

do_install() {
    install -d ${D}${nonarch_base_libdir}/firmware/nxp ${D}${nonarch_base_libdir}/firmware/mrvl
    install -m 0644 ${S}/FwImage_8997_SD/*   ${D}${nonarch_base_libdir}/firmware/nxp/
    install -m 0644 ${S}/FwImage_8997_PCIE/* ${D}${nonarch_base_libdir}/firmware/nxp/

    # mainline mwifiex (drivers/net/wireless/marvell/mwifiex/sdio.h, pcie.h)
    # loads from mrvl/ under the pre-6.12 file names; btnxpuart takes
    # nxp/uart8997_bt_v4.bin, which is installed above under that name.
    ln -s ../nxp/sduart8997_combo_v4.bin   ${D}${nonarch_base_libdir}/firmware/mrvl/sdiouart8997_combo_v4.bin
    ln -s ../nxp/sd8997_wlan_v4.bin        ${D}${nonarch_base_libdir}/firmware/mrvl/sd8997_wlan_v4.bin
    ln -s ../nxp/pcieuart8997_combo_v4.bin ${D}${nonarch_base_libdir}/firmware/mrvl/pcieuart8997_combo_v4.bin
    ln -s ../nxp/pcie8997_wlan_v4.bin      ${D}${nonarch_base_libdir}/firmware/mrvl/pcie8997_wlan_v4.bin
}

FILES:${PN} = "${nonarch_base_libdir}/firmware"
INSANE_SKIP:${PN} += "arch"
