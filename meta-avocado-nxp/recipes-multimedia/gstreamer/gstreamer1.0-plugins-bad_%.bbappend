# See gstreamer1.0_%.bbappend in this dir for rationale.
PACKAGE_ARCH = "${MACHINE_ARCH}"

# The NXP forks call add_dtrc_meta from the i.MX wayland-protocols, which
# meta-freescale now ships as wayland-protocols-imx. Its own .imx recipes
# inherit use-imx-wayland-protocols; meta-imx's copies of the same recipes,
# which shadow them, don't yet.
inherit_defer ${@'use-imx-wayland-protocols' if d.getVar('PV').endswith('.imx') else ''}
