# The journald input plugin backs the persistent /var/log/journal rolling
# window, so it has to be present in every build that ships fluentbit, not
# present by luck. Upstream leaves FLB_IN_SYSTEMD unset and lets cmake auto-
# detect libsystemd: the plugin is built when the probe finds it and silently
# dropped when it does not, with no build failure to notice. Pin it.
#
# Key the pin on the same DISTRO_FEATURES check that gates systemd entering
# DEPENDS upstream. The avocado-container distro removes systemd and sets
# INIT_MANAGER none, so forcing On there would fail configure looking for a
# libsystemd that was never a dependency.
EXTRA_OECMAKE += "${@bb.utils.contains('DISTRO_FEATURES', 'systemd', '-DFLB_IN_SYSTEMD=On', '-DFLB_IN_SYSTEMD=Off', d)}"
