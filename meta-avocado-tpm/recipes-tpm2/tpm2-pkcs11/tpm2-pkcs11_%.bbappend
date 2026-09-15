# https://git.yoctoproject.org/meta-security/commit/?id=cd729862f68152bc76db02cd4a93ca12a9424f88
BBCLASSEXTEND = "native nativesdk"

# Upstream's hardening probe compiles a conftest with `-Wformat-security
# -Werror` and nothing else, and GCC refuses that combination outright:
#
#   cc1: error: '-Wformat-security' ignored without '-Wformat'
#        [-Werror=format-security]
#
# so the probe reports "no" and configure aborts with "Cannot enable
# -Wformat-security, consider configuring with --disable-hardening".
#
# Only the native variant fails, which is why this looks machine-specific and
# is not: the target build already carries -Wformat from OE's security flags,
# so the probe finds it in CFLAGS and passes. A native build gets BUILD_CFLAGS,
# which do not include it, so the probe compiles -Wformat-security alone.
#
# Supplying -Wformat rather than the --disable-hardening the error suggests:
# taking that suggestion would turn the whole hardening set off for the native
# tool to work around a probe that is testing the wrong flag combination. This
# makes the probe pass and leaves hardening on.
CFLAGS:append:class-native = " -Wformat"
