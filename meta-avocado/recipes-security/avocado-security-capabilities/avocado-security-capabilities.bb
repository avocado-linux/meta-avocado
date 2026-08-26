SUMMARY = "This machine's AVOCADO_SECURITY_CAPABILITIES declaration, as a package"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

# /etc/avocado-security-capabilities is what cryptsetup-var.sh and
# optee-ftpm-setup.sh consult before touching a device, and what posture
# reporting reads. avocado-security-capabilities.bbclass writes it into the
# Yocto rootfs/initramfs images via ROOTFS_POSTPROCESS_COMMAND - but avocado-cli
# never ships those images: it composes the rootfs and initramfs from the
# feed's RPMs (avocado-pkg-rootfs / -initramfs are metapackages). Measured on a
# jetson-orin-nano built from a declaring machine: the file was absent. So the
# declaration has to travel as a package. Same content, same source variable,
# one more delivery path; the bbclass keeps the ConfigParsed guard and the
# image artifact (which now simply agrees with this package).
#
# An unmigrated machine (variable unset) yields an empty package rather than a
# fabricated empty file - "nothing to read" stays distinguishable from "declares
# nothing", exactly as in the bbclass.

PACKAGE_ARCH = "${MACHINE_ARCH}"
ALLOW_EMPTY:${PN} = "1"

# "1" when the machine declares (even an empty list); "0" when unmigrated.
AVOCADO_SECURITY_CAPABILITIES_DECLARED = "${@'1' if d.getVar('AVOCADO_SECURITY_CAPABILITIES') is not None else '0'}"

do_install() {
    if [ "${AVOCADO_SECURITY_CAPABILITIES_DECLARED}" = "1" ]; then
        install -d ${D}${sysconfdir}
        printf '%s\n' "${AVOCADO_SECURITY_CAPABILITIES}" > ${D}${sysconfdir}/avocado-security-capabilities
    fi
}
do_install[vardeps] += "AVOCADO_SECURITY_CAPABILITIES AVOCADO_SECURITY_CAPABILITIES_DECLARED"

FILES:${PN} = "${sysconfdir}/avocado-security-capabilities"
