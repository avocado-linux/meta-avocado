SUMMARY = "KAB publishtool"
LICENSE = "CLOSED"

PUBLISHTOOL_MAVEN_BASE = "https://kondra.mycloudrepo.io/public/repositories/kos-public/com/kosdev/kos/studio/v1/studio.v1.client.tools.publishtool"
PUBLISHTOOL_JAR = "studio.v1.client.tools.publishtool-${PV}.jar"

SRC_URI = "${PUBLISHTOOL_MAVEN_BASE}/${PV}/${PUBLISHTOOL_JAR};downloadfilename=${PUBLISHTOOL_JAR};unpack=false \
    file://publishtool.sh"

SRC_URI[sha256sum] = "dfe7b702297555dd94987c4d1945006fc5cff96f4ec2b7a9dba1b7528511be92"

S = "${UNPACKDIR}"

RDEPENDS:${PN} = "openjdk-17-jre kabtool"

do_configure[noexec] = "1"
do_patch[noexec] = "1"
do_compile[noexec] = "1"

PUBLISHTOOL_LIBDIR = "${libdir}/publishtool"

do_install() {
    install -d ${D}${PUBLISHTOOL_LIBDIR}
    install -m 0644 ${UNPACKDIR}/${PUBLISHTOOL_JAR} ${D}${PUBLISHTOOL_LIBDIR}/publishtool.jar

    install -d ${D}${bindir}
    sed -e 's|@LIBDIR@|${PUBLISHTOOL_LIBDIR}|g' ${UNPACKDIR}/publishtool.sh > ${D}${bindir}/publishtool
    chmod 0755 ${D}${bindir}/publishtool
}

FILES:${PN} = "${bindir}/publishtool \
    ${PUBLISHTOOL_LIBDIR}/publishtool.jar"

BBCLASSEXTEND = "nativesdk"
