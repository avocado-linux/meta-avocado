FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

# `+=`, not `:append =`: three `SRC_URI:append = "..."` lines in one file are
# three assignments to the same override, so only the last one ever took
# effect - the secureboot and module-signing fragments were silently dropped
# whenever encrypted-var was also on. Vendor bbappends that add their own
# fragments hit the same collision.

SRC_URI += "${@bb.utils.contains('DISTRO_FEATURES', 'secureboot', ' file://dm-verity.cfg', '', d)}"
# CONFIG_MODULE_SIG_FORCE makes the kernel refuse every unsigned module, so it
# is only safe once feed and out-of-tree modules are signed with the key the
# kernel embeds and that key is stable across kernel rebuilds and A/B updates.
# This tree sets no MODULE_SIG_KEY and no package signing, so the key is
# regenerated per build. Gated on the opt-in 'module-signing' feature rather
# than on 'security', which is on by default for every machine.
SRC_URI += "${@bb.utils.contains('DISTRO_FEATURES', 'module-signing', ' file://modsign.cfg', '', d)}"
# dm-crypt + LUKS ciphers for the encrypted /var (cryptsetup-var). Built
# whenever the machine declares the encrypted-var capability: whether a device
# actually encrypts is decided per runtime by avocado.yaml (var.encrypt), so the
# kernel has to be able to either way. See docs/security-capabilities.md.
SRC_URI += "${@bb.utils.contains('AVOCADO_SECURITY_CAPABILITIES', 'encrypted-var', ' file://dm-crypt.cfg', '', d)}"
