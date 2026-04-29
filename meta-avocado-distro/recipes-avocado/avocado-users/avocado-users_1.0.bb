DESCRIPTION = "Avocado Linux users"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

inherit allarch

# Configuration variable to allow root login with empty password
# Set AVOCADO_DEV_ROOT_LOGIN = "1" in local.conf to enable
AVOCADO_DEV_ROOT_LOGIN ??= "0"

SRC_URI = " \
  file://passwd \
  file://shadow \
  file://group \
  file://gshadow \
"

# Only file:// fetches — wrynose no longer auto-creates ${S}, so set
# it explicitly to UNPACKDIR (where bitbake places file:// files).
S = "${UNPACKDIR}"

do_install() {
    install -d ${D}${sysconfdir}
    install -m 0644 ${UNPACKDIR}/passwd ${D}${sysconfdir}/passwd
    install -m 0644 ${UNPACKDIR}/group ${D}${sysconfdir}/group
    install -m 0644 ${UNPACKDIR}/gshadow ${D}${sysconfdir}/gshadow

    # Handle shadow file with optional root login configuration
    if [ "${AVOCADO_DEV_ROOT_LOGIN}" = "1" ]; then
        # Enable root login with empty password by setting empty password field
        sed 's/^root:\*:/root::/' ${UNPACKDIR}/shadow > ${D}${sysconfdir}/shadow
        bbwarn "Root login with empty password is enabled. This is insecure and should only be used for development!"
    else
        # Use default shadow file (root login disabled)
        install -m 0644 ${UNPACKDIR}/shadow ${D}${sysconfdir}/shadow
    fi
}
do_install[vardeps] += "AVOCADO_DEV_ROOT_LOGIN"
