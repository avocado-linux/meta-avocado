FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI:append = "${@bb.utils.contains('DISTRO_FEATURES', 'secureboot', ' file://dm-verity.cfg', '', d)}"
SRC_URI:append = "${@bb.utils.contains('DISTRO_FEATURES', 'security', ' file://modsign.cfg', '', d)}"
# dm-crypt + LUKS ciphers for the encrypted /var (cryptsetup-var). Gated on the
# opt-in 'encrypted-var' feature; the shared dm-crypt.cfg is arch-agnostic so
# x86, arm and the NXP boards all pick it up when encryption is enabled.
SRC_URI:append = "${@bb.utils.contains('DISTRO_FEATURES', 'encrypted-var', ' file://dm-crypt.cfg', '', d)}"
