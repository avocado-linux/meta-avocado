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
# group; this adds the userland that makes wlan0 usable on a networkd image,
# the supplicant for WPA-PSK, iw for diagnostics, the regulatory database and
# the CYW43455/43456 firmware, which is otherwise only in the extra group.
RDEPENDS:${PN}:append:raspberrypi5 = " \
    wpa-supplicant \
    iw \
    wireless-regdb-static \
    linux-firmware-rpidistro-bcm43455 \
    linux-firmware-rpidistro-bcm43456 \
"
