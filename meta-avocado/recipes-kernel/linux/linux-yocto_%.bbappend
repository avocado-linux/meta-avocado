FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI:append = "${@bb.utils.contains('DISTRO_FEATURES', 'secureboot', ' file://dm-verity.cfg', '', d)}"
SRC_URI:append = "${@bb.utils.contains('DISTRO_FEATURES', 'security', ' file://modsign.cfg', '', d)}"
# dm-crypt + LUKS ciphers for the encrypted /var (cryptsetup-var). Gated on
# 'security' (default-on); the shared dm-crypt.cfg is arch-agnostic so x86,
# arm and the NXP boards all pick it up (i.MX93 also layers its CAAM cfg).
SRC_URI:append = "${@bb.utils.contains('DISTRO_FEATURES', 'security', ' file://dm-crypt.cfg', '', d)}"
