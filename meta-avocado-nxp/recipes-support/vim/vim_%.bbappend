# The pinned oe-core vim enables the GTK GUI (gtkgui) whenever 'x11' is in
# DISTRO_FEATURES. vim's GTK GUI sources (gui_gtk_x11.c) include the X11-only
# <gdk/gdkx.h>, which is present with the community meta-freescale GTK (X11
# backend) but NOT with meta-imx's GTK, which NXP builds Wayland-only -- so
# the GUI build fails on meta-imx i.MX targets (e.g. ucm-imx8m-plus). A
# headless embedded image has no use for a GUI vim regardless; drop it. vim
# keeps its terminal/X11-clipboard features (the 'x11' PACKAGECONFIG).
PACKAGECONFIG:remove = "gtkgui"
