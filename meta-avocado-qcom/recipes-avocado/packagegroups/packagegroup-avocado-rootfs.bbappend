# OE-core's 90-systemd.preset enables the bare `getty@.service` template, which
# systemd instantiates as getty@getty.service; agetty then fails to open
# /dev/getty and the board boots `degraded`. systemd-serial-console-preset
# disables that template. Neither rubikpi3 nor rb3gen2 has a virtual console:
# the login prompt comes from serial-getty@ttyMSM0.service via
# systemd-getty-generator.
#
# systemd-rubikpi3-masks carries the same preset, but it reaches a runtime only
# through packagegroup-avocado-qcom-extra (feed-only), and
# packagegroup-avocado-rootfs.bb deliberately does not expand
# MACHINE_ESSENTIAL_EXTRA_RDEPENDS, so a runtime without that group never got
# it. The preset alone is enough in the rootfs: it is present for the first-boot
# preset-all, which is what the masks package has to work around when it
# arrives later in an extension. Raspberry Pi and i.MX wire the fix the same way.
RDEPENDS:${PN}:append:rubikpi3 = " systemd-serial-console-preset"
RDEPENDS:${PN}:append:rb3gen2 = " systemd-serial-console-preset"
