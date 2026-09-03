DESCRIPTION = "Avocado SDK configuration files"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

PV = "${SDK_VERSION}"

SRC_URI = " \
    file://dnf.conf \
"

S = "${WORKDIR}"

FILES:${PN} += "${sysconfdir}/yum.repos.d/avocado-sdk.repo"

inherit update-alternatives

ALTERNATIVE:${PN} += "dnf_conf dnf_vars_arch rpm_platform rpmrc"
ALTERNATIVE_PRIORITY:${PN} = "100"
ALTERNATIVE_LINK_NAME[dnf_vars_arch] = "${sysconfdir}/dnf/vars/arch"
ALTERNATIVE_LINK_NAME[dnf_conf] = "${sysconfdir}/dnf/dnf.conf"
ALTERNATIVE_LINK_NAME[rpm_platform] = "${sysconfdir}/rpm/platform"
ALTERNATIVE_LINK_NAME[rpmrc] = "${sysconfdir}/rpmrc"

# The [avocado-sdk] section is generated rather than shipped as a static file
# so that the verification switches reach it. A hardcoded gpgcheck=0 would stay
# unverified while every generated section switched over, and the repository
# left out is the one every SDK container reads.
python do_compile() {
    import os
    # Imported and called fully qualified, not aliased. BitBake records the
    # literal call spelling and matches it against the registered name
    # avocado_sdk_metadata.repoconf.<func>; an alias never matches, so the
    # renderer's source would drop out of this task's hash.
    import avocado_sdk_metadata.repoconf

    # Package signatures. Distinct from AVOCADO_REPO_METADATA_GPGCHECK, which
    # is the one a signed repomd.xml needs. See
    # meta-avocado/lib/avocado_sdk_metadata/repoconf.py for why they differ.
    gpg_check = d.getVar('AVOCADO_REPO_GPGCHECK') or '0'
    repo_metadata_gpg_check = d.getVar('AVOCADO_REPO_METADATA_GPGCHECK') or '0'

    out_dir = os.path.join(d.getVar('WORKDIR'), 'generated-files')
    os.makedirs(out_dir, exist_ok=True)

    with open(os.path.join(out_dir, 'avocado-sdk.repo'), 'w') as repo_f:
        repo_f.write(avocado_sdk_metadata.repoconf.render_sdk_repo_section(
            gpgcheck=gpg_check,
            repo_gpgcheck=repo_metadata_gpg_check,
        ))
}

do_install() {
    # Add Avocado SDK repo
    install -d ${D}${sysconfdir}/yum.repos.d
    install -m 0644 ${WORKDIR}/generated-files/avocado-sdk.repo ${D}${sysconfdir}/yum.repos.d/avocado-sdk.repo

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

