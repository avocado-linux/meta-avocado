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

# The shipped files REPLACE /etc/passwd and /etc/group wholesale, so any system
# user a package creates through the useradd class is silently discarded. That
# is why sshd is listed here: oe-core's openssh declares
# USERADD_PARAM:${PN}-sshd = "--system --no-create-home --home-dir /var/run/sshd
# --shell /bin/false --user-group sshd", and without the account OpenSSH refuses
# to start at all - it exits before writing a banner or a log line, so the only
# symptom is every ssh connection dying at kex_exchange_identification with
# nothing in the journal to explain it. The entry below mirrors that
# USERADD_PARAM's home directory and shell; keep them in step.
#
# devtool-debt: sshd is hand-copied here rather than the clobber being fixed.
# Ceiling: exactly the packages whose users someone has noticed and transcribed.
# Upgrade trigger: a second package needs a useradd-created system account, or
# any account here drifts from the USERADD_PARAM it mirrors. The real fix is to
# stop shipping a whole /etc/passwd - pin only the uid/gid this distro cares
# about via sysusers.d or USERADDEXTENSION and let useradd own the rest - which
# is a change to how every Avocado image gets its users and wants its own
# verification, not a line in this file.
do_install() {
    install -d ${D}${sysconfdir}
    install -m 0644 ${WORKDIR}/passwd ${D}${sysconfdir}/passwd
    install -m 0644 ${WORKDIR}/group ${D}${sysconfdir}/group
    install -m 0644 ${WORKDIR}/gshadow ${D}${sysconfdir}/gshadow

    # Handle shadow file with optional root login configuration
    if [ "${AVOCADO_DEV_ROOT_LOGIN}" = "1" ]; then
        # Enable root login with empty password by setting empty password field
        sed 's/^root:\*:/root::/' ${WORKDIR}/shadow > ${D}${sysconfdir}/shadow
        bbwarn "Root login with empty password is enabled. This is insecure and should only be used for development!"
    else
        # Use default shadow file (root login disabled)
        install -m 0644 ${WORKDIR}/shadow ${D}${sysconfdir}/shadow
    fi
}
do_install[vardeps] += "AVOCADO_DEV_ROOT_LOGIN"
