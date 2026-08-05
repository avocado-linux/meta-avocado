# systemctl links against the host's PAM and then cannot compile against it:
#
#   src/shared/pam-util.c:3:10: fatal error: security/pam_ext.h: No such file
#
# The configure log shows why the usual sandboxing does not catch this:
#
#   Run-time dependency pam found: NO (tried pkgconfig and cmake)
#   Library pam found: YES
#
# pkg-config is correctly confined to the recipe sysroot, so dependency('pam')
# at meson.build:1250 fails. systemd then falls back to cc.find_library('pam')
# at :1254, and a raw linker search is not confined - it resolves against the
# host's /usr/lib/libpam.so. The header is not on the task's include path, so
# the leak only surfaces at compile time.
#
# This bites on any host that ships the PAM development headers. On Arch that
# is unconditional, because systemd itself depends on pam.
#
# Depending on libpam-native cannot fix it: DISTRO_FEATURES_FILTER_NATIVE
# restricts native builds to a small allowlist that never includes "pam" or
# "systemd", so libpam-native's ANY_OF_DISTRO_FEATURES = "pam systemd" check
# always fails for -native and libpam-native is unconditionally unavailable
# ("Nothing PROVIDES") regardless of any DEPENDS.
#
# pam is a 'feature' option (meson_options.txt:421), so disabling it makes
# get_option('pam') disabled and skips both the dependency() and the
# find_library() fallback. This recipe builds only systemctl, which does not
# authenticate anything.
EXTRA_OEMESON += "-Dpam=disabled"
