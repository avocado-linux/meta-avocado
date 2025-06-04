SUMMARY = "Installs the Avocado SDK entrypoint script"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

SRC_URI = "file://entrypoint.sh \
           file://avocado-repo \
           file://avocado-build \
					 file://avocado-sdk-common.sh \
           file://avocado-run-qemu \
"

S = "${WORKDIR}"

COMPATIBLE_MACHINE = "avocado-container"

RDEPENDS:${PN} += "bash"

do_install() {
	install -d ${D}${bindir}
	install -m 0755 ${S}/entrypoint.sh ${D}${bindir}
	install -m 0755 ${S}/avocado-repo ${D}${bindir}
	install -m 0755 ${S}/avocado-build ${D}${bindir}
	install -m 0755 ${S}/avocado-sdk-common.sh ${D}${bindir}
	install -m 0755 ${S}/avocado-run-qemu ${D}${bindir}
	sed -i "s|__SDK_INSTALL_PATH__|${SDKPATHNATIVE}|g" ${D}${bindir}/entrypoint.sh
}

FILES:${PN} += "${bindir}/entrypoint.sh \
                ${bindir}/avocado-repo \
                ${bindir}/avocado-build \
								${bindir}/avocado-sdk-common.sh \
                ${bindir}/avocado-run-qemu \
"
