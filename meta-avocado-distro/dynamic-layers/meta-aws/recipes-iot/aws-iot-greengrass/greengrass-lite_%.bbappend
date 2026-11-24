# Greengrass Lite keeps its state in ${gg_workingdir} (/var/lib/greengrass),
# which the recipe creates at install time. An extension does not deliver
# /var, so tmpfiles creates it, owned by the nucleus user, at boot.
do_install:append() {
    install -d ${D}${nonarch_libdir}/tmpfiles.d
    echo "d ${gg_workingdir} 0755 ${gg_user} ${gg_group} -" \
        > ${D}${nonarch_libdir}/tmpfiles.d/greengrass-lite.conf
}

FILES:${PN} += "${nonarch_libdir}/tmpfiles.d/greengrass-lite.conf"
