# setup-nv-boot-control.service sets DefaultDependencies=no and orders
# itself after nothing, so it can run before the module EEPROM is
# readable. On L4T 6.8 the Tegra I2C controllers load from udev and
# i2c-dev from modules-load.d, and the unit lost that race on every boot.
FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

SRC_URI += "file://50-avocado-wait-for-boardspec.conf"

# FILES:${PN}-service already takes all of ${systemd_system_unitdir}.
do_install:append() {
    install -d ${D}${systemd_system_unitdir}/setup-nv-boot-control.service.d
    install -m 0644 ${UNPACKDIR}/50-avocado-wait-for-boardspec.conf \
        ${D}${systemd_system_unitdir}/setup-nv-boot-control.service.d/
}
