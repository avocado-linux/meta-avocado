# OE-core's 90-systemd.preset enables the bare `getty@.service` template, which
# systemd instantiates as getty@getty.service; agetty then fails to open
# /dev/getty and every Raspberry Pi boots `degraded`. systemd-serial-console-
# preset disables that template. No virtual-console getty is enabled on these
# images today, so nothing that worked is lost: the login prompt comes from
# serial-getty@<console>.service via systemd-getty-generator.
#
# It has to be pulled in here because packagegroup-avocado-rootfs.bb
# deliberately does not expand MACHINE_ESSENTIAL_EXTRA_RDEPENDS. i.MX and the
# Jetson boards wire the same fix the same way.
RDEPENDS:${PN}:append:rpi = " systemd-serial-console-preset"

# Wi-Fi on the Pi 5: the brcmfmac modules come from the kernel's rootfs module
# group; this adds the supplicant for WPA-PSK, iw for diagnostics, the
# regulatory database and the CYW43455/43456 firmware. The machine conf
# defines the firmware list once; MACHINE_EXTRA_RRECOMMENDS reaches only the
# extra group, which is why the rootfs names it again here.
#
# This brings up the wlan0 netdev, not a connection. To join a network the
# image still has to supply, through an extension or confext since /etc is
# read-only: /etc/wpa_supplicant/wpa_supplicant-wlan0.conf, an enabled
# wpa_supplicant@wlan0 unit, and a systemd-networkd .network file matching
# wlan0.
#
# Bluetooth is out of scope: its firmware stays in the extra group only.
RDEPENDS:${PN}:append:raspberrypi5 = " \
    wpa-supplicant \
    iw \
    wireless-regdb-static \
    ${AVOCADO_RPI_WIFI_FIRMWARE} \
"
