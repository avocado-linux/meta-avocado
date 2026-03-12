SUMMARY = "KAB packaging and verification tool"
LICENSE = "CLOSED"

KABTOOL_MAVEN_BASE = "https://kondra.mycloudrepo.io/public/repositories/kos-public/com/kosdev/kos/studio/v1/studio.v1.client.tools.kabtool"
KABTOOL_JAR = "studio.v1.client.tools.kabtool-${PV}.jar"

SRC_URI = "${KABTOOL_MAVEN_BASE}/${PV}/${KABTOOL_JAR};downloadfilename=${KABTOOL_JAR};unpack=false \
    file://kabtool.sh"

SRC_URI[sha256sum] = "ef59982abfd32c670862190c22347d8ca3fc39f7140901cf017f58ff0b9a3421"

S = "${WORKDIR}"

RDEPENDS:${PN} = "openjdk-17-jre"

do_configure[noexec] = "1"
do_patch[noexec] = "1"
do_compile[noexec] = "1"

KABTOOL_LIBDIR = "${libdir}/kabtool"

do_install() {
    install -d ${D}${KABTOOL_LIBDIR}
    install -m 0644 ${WORKDIR}/${KABTOOL_JAR} ${D}${KABTOOL_LIBDIR}/kabtool.jar

    install -d ${D}${bindir}
    sed -e 's|@LIBDIR@|${KABTOOL_LIBDIR}|g' ${WORKDIR}/kabtool.sh > ${D}${bindir}/kabtool
    chmod 0755 ${D}${bindir}/kabtool
}

FILES:${PN} = "${bindir}/kabtool \
    ${KABTOOL_LIBDIR}/kabtool.jar"

BBCLASSEXTEND = "nativesdk"
