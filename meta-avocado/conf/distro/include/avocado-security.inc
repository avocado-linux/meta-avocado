# AVOCADO_SB_KEYS_DIR is deliberately NOT in BB_BASEHASH_IGNORE_VARS. The certs
# it points at are generated inside sb-keys' do_compile and never otherwise
# enter the task hash, so ignoring the variable's value collapses two
# genuinely different key directories to the same sstate signature - a build
# pointing at key dir A would get a package built from key dir B's certs
# served out of a shared sstate mirror, silently, with no symptom until the
# wrong key turned up on a device. Keeping the path in the hash costs a cache
# miss for every developer with a different AVOCADO_SB_KEYS_DIR; that is the
# safe failure mode for key material, not the collision.
AVOCADO_SB_KEYS_DIR ?= "${TOPDIR}/avocado-sb-keys"

# Global fail-loud check for security features requested via DISTRO_FEATURES
# against what the selected machine declares it can deliver. Same INHERIT +=
# shape as INHERIT += "avocado-sysusers" in conf/distro/avocado.conf:15;
# lives here rather than there because this file is the security-scoped
# include, already require'd from conf/distro/avocado.inc:56.
INHERIT += "avocado-security-capabilities"
