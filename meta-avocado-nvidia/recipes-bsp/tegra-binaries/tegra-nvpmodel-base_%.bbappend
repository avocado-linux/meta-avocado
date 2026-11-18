# One Orin NX / Orin Nano (P3767) image boots every module SKU, but the base
# recipe installs only ${NVPMODEL}.conf, so an 8GB Orin NX runs the 16GB power
# model. Ship every P3767 conf and pick one when nvpmodel.service starts, from
# the device-tree compatible, as NVIDIA's nvpower.sh does on JetPack. /etc is
# read-only here, so the pick lands in /run and /etc/nvpmodel.conf points
# there; until the pick runs, tmpfiles points it at the old single conf.
FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

SRC_URI += " \
    file://nvpmodel-select.sh \
    file://nvpmodel-select.conf \
    file://nvpmodel.tmpfiles \
"

do_install:append() {
    if [ "${TEGRA_BOARDID}" = "3767" ]; then
        if [ -n "${NVPMODEL_CONFIG_DEFAULT}" ]; then
            bbfatal "NVPMODEL_CONFIG_DEFAULT is a mode ID, and P3767 SKUs number their modes differently"
        fi
        install -m 0644 ${B}/etc/nvpmodel/nvpmodel_p3767_*.conf ${D}${sysconfdir}/nvpmodel/
        ln -sf ../run/nvpmodel.conf ${D}${sysconfdir}/nvpmodel.conf
        install -D -m 0755 ${UNPACKDIR}/nvpmodel-select.sh ${D}${libexecdir}/nvpmodel-select
        install -D -m 0644 ${UNPACKDIR}/nvpmodel-select.conf \
            ${D}${systemd_system_unitdir}/nvpmodel.service.d/avocado.conf
        install -D -m 0644 ${UNPACKDIR}/nvpmodel.tmpfiles \
            ${D}${nonarch_libdir}/tmpfiles.d/nvpmodel.conf
        sed -i -e 's,@NVPMODEL@,${NVPMODEL},g' \
            ${D}${libexecdir}/nvpmodel-select ${D}${nonarch_libdir}/tmpfiles.d/nvpmodel.conf
    fi
}

FILES:${PN} += " \
    ${libexecdir}/nvpmodel-select \
    ${systemd_system_unitdir}/nvpmodel.service.d \
    ${nonarch_libdir}/tmpfiles.d/nvpmodel.conf \
"
