FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI:append = "${@bb.utils.contains('DISTRO_FEATURES', 'secureboot', ' file://dm-verity.cfg', '', d)}"
# CONFIG_MODULE_SIG_FORCE makes the kernel refuse every unsigned module, so it
# is only safe once feed and out-of-tree modules are signed with the key the
# kernel embeds and that key is stable across kernel rebuilds and A/B updates.
# This tree sets no MODULE_SIG_KEY and no package signing, so the key is
# regenerated per build. Gated on the opt-in 'module-signing' feature rather
# than on 'security', which is on by default for every machine.
SRC_URI:append = "${@bb.utils.contains('DISTRO_FEATURES', 'module-signing', ' file://modsign.cfg', '', d)}"
# dm-crypt + LUKS ciphers for the encrypted /var (cryptsetup-var). Gated on the
# opt-in 'encrypted-var' feature; the shared dm-crypt.cfg is arch-agnostic so
# x86, arm and the NXP boards all pick it up when encryption is enabled.
SRC_URI:append = "${@bb.utils.contains('DISTRO_FEATURES', 'encrypted-var', ' file://dm-crypt.cfg', '', d)}"
