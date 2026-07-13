# pam-util.c unconditionally includes security/pam_ext.h. Depending on
# libpam-native cannot fix this: DISTRO_FEATURES_FILTER_NATIVE restricts
# native builds to a small allowlist that never includes "pam" or "systemd",
# so libpam-native's ANY_OF_DISTRO_FEATURES = "pam systemd" check always
# fails for -native and libpam-native is unconditionally unavailable
# ("Nothing PROVIDES") regardless of any DEPENDS. Disable PAM in this
# native-only build tool's own meson config instead; systemctl-native never
# needs real PAM integration on the build host.
EXTRA_OEMESON += "-Dpam=disabled"
