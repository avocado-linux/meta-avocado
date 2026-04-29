# Wrynose dropped OE-core's compat init-manager-none.inc (commit 0b4061c5d5,
# "conf: Switch to systemd by default and simplify init manager selection").
# defaultsetup.conf still does
#     require conf/distro/include/init-manager-${INIT_MANAGER}.inc
# so INIT_MANAGER = "none" now needs us to provide the file. We do this in
# meta-avocado so BBPATH finds it before OE-core/meta.
#
# avocado-container.conf is the only consumer (DISTRO = "avocado-container").
# It already explicitly sets VIRTUAL-RUNTIME_init_manager / _initscripts /
# _login_manager to "" before this is required, so the upstream defaults
# (??= sysvinit / initscripts / busybox) we used to override here are
# already pre-empted. Keep this file as a no-op marker.
