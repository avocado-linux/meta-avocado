# gtk+3 on NXP targets is built wayland-only; disable the GTK3/X11 GUI to
# avoid missing gdkx11 headers during compilation.
PACKAGECONFIG:remove = "gtkgui x11"
