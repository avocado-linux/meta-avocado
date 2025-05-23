DESCRIPTION = "Avocado SDK configuration files"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

SRC_URI = " \
    file://avocado-sdk.repo \
    file://dnf.conf \
"

S = "${WORKDIR}"

REPO_BASE = "${AVOCADO_REPO_BASE}"

FILES:${PN} += "${sysconfdir}/yum.repos.d/avocado-sdk.repo"

inherit update-alternatives

ALTERNATIVE:${PN} += "dnf_conf dnf_vars_arch rpm_platform rpmrc"
ALTERNATIVE_PRIORITY:${PN} = "100"
ALTERNATIVE_LINK_NAME[dnf_vars_arch] = "${sysconfdir}/dnf/vars/arch"
ALTERNATIVE_LINK_NAME[dnf_conf] = "${sysconfdir}/dnf/dnf.conf"
ALTERNATIVE_LINK_NAME[rpm_platform] = "${sysconfdir}/rpm/platform"
ALTERNATIVE_LINK_NAME[rpmrc] = "${sysconfdir}/rpmrc"

do_install() {
    # Add Avocado SDK repo
    install -d ${D}${sysconfdir}/yum.repos.d
    install -m 0644 ${WORKDIR}/avocado-sdk.repo ${D}${sysconfdir}/yum.repos.d/avocado-sdk.repo
    sed -i "s|{REPO_BASE}|${REPO_BASE}|g" ${D}${sysconfdir}/yum.repos.d/avocado-sdk.repo

    install -d ${D}${sysconfdir}/dnf
    install -m 644 ${WORKDIR}/dnf.conf ${D}${sysconfdir}/dnf/dnf.conf.${PN}

    install -d ${D}${sysconfdir}/dnf/vars
    echo "${TARGET_ARCH}_avocadosdk:all_avocadosdk:avocado_nativesdk" > ${D}${sysconfdir}/dnf/vars/arch.${PN}

    # Install RPM platform override
    install -d ${D}${sysconfdir}/rpm
    echo "${TARGET_ARCH}_avocadosdk-avocado-linux" > ${D}${sysconfdir}/rpm/platform.${PN}

    # Install custom rpmrc
    cat <<EOF > ${D}${sysconfdir}/rpmrc.${PN}
arch_compat: ${TARGET_ARCH}_avocadosdk: all any noarch ${TARGET_ARCH} ${DEFAULTTUNE} all_avocadosdk
buildarch_compat: ${TARGET_ARCH}_avocadosdk: noarch
EOF
}

