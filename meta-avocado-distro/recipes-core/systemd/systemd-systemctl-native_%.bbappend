# Host build: the buildtools gcc is sandboxed to its own --sysroot and does not
# search the host /usr/include. systemd's PAM detection defaults to auto and
# finds the host libpam, but the compile of src/shared/pam-util.c then fails on
# the missing security/pam_ext.h. systemctl-native has no use for PAM, so drop
# it outright rather than pulling in libpam-native.
EXTRA_OEMESON += "-Dpam=disabled"
