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

# Same reasoning applies to the AHAB PKI tree: avocado-ahab-sign.bbclass's
# avocado_ahab_sign() reads the SRK certs and private keys straight off
# AVOCADO_AHAB_KEYS_DIR inside do_compile[postfuncs], with no [file-checksums]
# hashing the actual cert/key content - so excluding the path here would
# collapse two different SRK sets to one sstate signature, the same collision
# just removed above, on the boot image's hardware root of trust rather than
# the UEFI certs. AVOCADO_AHAB_SPSDK_BINDIR gets the same treatment for the
# same reason: a different SPSDK install can mean a different SPSDK version,
# and nothing here pins that version, so its path is exactly the kind of
# "different input, different output" signal BB_BASEHASH_IGNORE_VARS is not
# safe to throw away either. Neither var gets a default (see avocado-ahab-
# sign.bbclass) - AHAB keys are the root of trust burned into a fuse and
# cannot be conjured by the build, so a default that worked would be a
# default anyone could sign against.

# Global fail-loud check for security features requested via DISTRO_FEATURES
# against what the selected machine declares it can deliver. Same INHERIT +=
# shape as INHERIT += "avocado-sysusers" in conf/distro/avocado.conf:15;
# lives here rather than there because this file is the security-scoped
# include, already require'd from conf/distro/avocado.inc:56.
INHERIT += "avocado-security-capabilities"
