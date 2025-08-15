DESCRIPTION = "Avocado Linux users"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

inherit allarch

SRC_URI = " \
  file://passwd \
  file://shadow \
  file://group \
  file://gshadow \
"

do_install() {
    install -d ${D}${sysconfdir}
    install -m 0644 ${WORKDIR}/passwd ${D}${sysconfdir}/passwd
    install -m 0644 ${WORKDIR}/shadow ${D}${sysconfdir}/shadow
    install -m 0644 ${WORKDIR}/group ${D}${sysconfdir}/group
    install -m 0644 ${WORKDIR}/gshadow ${D}${sysconfdir}/gshadow
}
