# Generate and keep the SSH host keys on /var, not on the read-only rootfs.
#
# sshd resolves its host keys to ${sysconfdir}/ssh. On an Avocado image that
# path is read-only, so sshd_check_keys cannot create a key there: the unit
# fails, sshd starts with no host key, and every client is dropped at key
# exchange with "Connection reset by peer". /var is writable and persistent,
# so a key generated there survives a reboot - which is what a client's
# known_hosts, and `avocado container dev up` reconnecting to a device that
# has rebooted, both depend on.
#
# Done here rather than as a drop-in in sshd_config.d because HostKey
# ACCUMULATES: a drop-in adds paths, it does not replace them, so the
# unreachable ${sysconfdir} entries would stay in the list and
# sshd_check_keys would keep failing on them.
#
# Complementary to, not redundant with, the SYSCONFDIR=/var/lib/ssh line that
# avocado-image-rootfs.bb appends to /etc/default/ssh. SYSCONFDIR only decides
# where sshd_check_keys does its mkdir -p; the key paths themselves come from
# `sshd -G` reading these HostKey lines, which is why that append alone left
# keys being written to ${sysconfdir} and failing. The sshd-dev extension
# avoids the problem by shipping a whole sshd_config of its own, so this gap
# only shows on an image carrying base-image openssh.
#
# The two branches below are what makes this file portable across the openssh
# versions in the layer. 10.3p1 rewrites sshd_config's HostKey lines itself
# from OPENSSH_HOST_KEY_DIR, one per key type enabled in PACKAGECONFIG, so
# rewriting in place is what preserves those gates. 9.6p1 leaves the lines
# commented and rewrites only sshd_config_readonly, so sshd falls back to its
# compiled-in defaults and there is nothing for a sed to match - naming the
# keys is the only way to move them. Picking one branch unconditionally breaks
# the other half silently: the sed is a no-op on 9.6p1, and the explicit list
# would resurrect a key type PACKAGECONFIG had turned off on 10.3p1.
do_install:append() {
    if [ ! -f ${D}${sysconfdir}/ssh/sshd_config ]; then
        return 0
    fi

    if grep -q '^HostKey ' ${D}${sysconfdir}/ssh/sshd_config; then
        sed -i 's|^HostKey .*/ssh_host_|HostKey /var/lib/ssh/ssh_host_|' \
            ${D}${sysconfdir}/ssh/sshd_config
    else
        # Written out rather than looped: bitbake expands ${...} in a shell
        # function itself, so a ${t} loop variable would be its syntax, not
        # the shell's.
        printf '%s\n' \
            'HostKey /var/lib/ssh/ssh_host_rsa_key' \
            'HostKey /var/lib/ssh/ssh_host_ecdsa_key' \
            'HostKey /var/lib/ssh/ssh_host_ed25519_key' \
            >> ${D}${sysconfdir}/ssh/sshd_config
    fi
}
