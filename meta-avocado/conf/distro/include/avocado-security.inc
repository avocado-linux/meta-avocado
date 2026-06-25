# Per-developer key paths are excluded from sstate hash inputs so two build
# hosts with identical key material but different absolute paths produce the
# same sstate hash.  Without this, every developer who places keys under a
# different TOPDIR would get a cache miss even though the resulting binaries
# are identical.
AVOCADO_SB_KEYS_DIR ?= "${TOPDIR}/avocado-sb-keys"

BB_BASEHASH_IGNORE_VARS:append = " AVOCADO_SB_KEYS_DIR"
