# The nucleus writes its root at runtime (deployments, its own updates, logs,
# config), and an Avocado root filesystem is read-only while an extension
# delivers only /usr, /opt and /etc. So the recipe's /greengrass/v2 tree is
# installed under /usr as a read-only copy, and the root the nucleus runs from
# is /var/lib/greengrass-nucleus, laid out by tmpfiles before each start:
#
#   - the image's nucleus is linked in as the init alternative on every start,
#     so an OS update that ships a new nucleus is the one that runs;
#   - alts/current and config.yaml are created only when missing, so a
#     nucleus Greengrass deployed itself, and a provisioned config, stay put.
#
# The loader takes its root from the path it is started by, so the service
# starts it through /var. Not enabled at boot: an extension that wants
# Greengrass lists greengrass.service and supplies the device's config.
GG_BASENAME = "usr/share/greengrass/v2"
# Not under /var/lib/greengrass: Greengrass Lite owns that as its own user,
# and tmpfiles refuses a root-owned path below it as an unsafe transition.
GG_VAR_ROOT = "/var/lib/greengrass-nucleus"

do_install:append() {
    nucleus=packages/artifacts-unarchived/aws.greengrass.Nucleus/${PV}/aws.greengrass.nucleus

    install -d ${D}${nonarch_libdir}/tmpfiles.d
    cat > ${D}${nonarch_libdir}/tmpfiles.d/greengrass-bin.conf <<TMPFILES
d ${GG_VAR_ROOT} 0755 root root -
d ${GG_VAR_ROOT}/config 0755 root root -
d ${GG_VAR_ROOT}/alts/init 0755 root root -
d ${GG_VAR_ROOT}/packages/artifacts-unarchived/aws.greengrass.Nucleus/${PV} 0755 root root -
L+ ${GG_VAR_ROOT}/$nucleus - - - - /${GG_BASENAME}/$nucleus
L+ ${GG_VAR_ROOT}/alts/init/distro - - - - ${GG_VAR_ROOT}/$nucleus
L ${GG_VAR_ROOT}/alts/current - - - - ${GG_VAR_ROOT}/alts/init
C ${GG_VAR_ROOT}/config/config.yaml - - - - /${GG_BASENAME}/config/config.yaml
TMPFILES

    unit=${D}${systemd_unitdir}/system/greengrass.service
    sed -i -e "s,/${GG_BASENAME}/alts/current,${GG_VAR_ROOT}/alts/current,g" $unit
    sed -i -e "/^ExecStart=/i ExecStartPre=systemd-tmpfiles --create greengrass-bin.conf" $unit
}

FILES:${PN} += "${nonarch_libdir}/tmpfiles.d/greengrass-bin.conf"

SYSTEMD_AUTO_ENABLE = "disable"

# meta-aws turns fleet provisioning on whenever ptest is, which pulls in its
# plugin, installed under /greengrass where an extension cannot deliver it, and
# useful only with claim certificates baked in per product.
PACKAGECONFIG:remove = "fleetprovisioning"
